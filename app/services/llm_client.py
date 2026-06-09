from __future__ import annotations

from importlib import import_module
from time import monotonic, sleep
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.services.api_key_rotation import APIKeyRotator, get_shared_rotator
from app.services.llm_attempts import llm_attempt_failure_category, summarize_llm_attempts
from app.services.llm_models import (
    gemini_vision_model_candidates,
    is_vision_model_candidate,
    litellm_key_candidates,
    litellm_model_candidates,
    litellm_model_requires_api_key,
)
from app.services.llm_observability import attach_llm_observability as _attach_llm_observability
from app.services.llm_provider_call_mixin import LLMProviderCallMixin
from app.services.llm_quota import LLMQuotaGovernanceService
from app.services.llm_quota_routing import LLMQuotaRoutingMixin
from app.services.llm_runtime import (
    DEFAULT_BASE_RETRY_DELAY_SECONDS,
    DEFAULT_MAX_RETRIES_PER_KEY,
    DEFAULT_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_TOTAL_TIMEOUT_SECONDS,
    LLMResult,
    RETRYABLE_HTTP_STATUSES as RETRYABLE_HTTP_STATUSES,
    ROTATABLE_HTTP_STATUSES as ROTATABLE_HTTP_STATUSES,
    _model_quota_cooldowns as _model_quota_cooldowns,
    _model_quota_cooldowns_lock as _model_quota_cooldowns_lock,
    llm_attempt_record as _llm_attempt_record,
    llm_error_retryable as _llm_error_retryable,
    llm_failure_result as _llm_failure_result,
    llm_retry_delay_seconds as _llm_retry_delay_seconds,
    llm_should_stop_after_status as _llm_should_stop_after_status,
    llm_success_result as _llm_success_result,
)
from app.services.llm_text_generation_mixin import LLMTextGenerationMixin

__all__ = [
    "APIKeyRotator",
    "LLMClient",
    "LLMResult",
    "get_shared_rotator",
    "llm_attempt_failure_category",
    "summarize_llm_attempts",
]


class LLMClient(LLMQuotaRoutingMixin, LLMProviderCallMixin, LLMTextGenerationMixin):
    """Provider boundary for Gemini/Gemma analysis.

    The MVP keeps this adapter deliberately thin. In production, put provider-specific
    SDK calls here and keep prompts, evidence, and whitelist checks outside the model.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.rotator = get_shared_rotator(self.settings.gemini_api_keys)
        self._quota_summary_cache: dict[str, object] | None = None

    def generate(self, prompt: str) -> str:
        result = self.generate_with_metadata(prompt)
        if result.fallback:
            return result.text
        key_note = (
            f"Gemini API key pool index：{result.key_index}"
            if result.key_index is not None
            else "Gemini API"
        )
        provider_note = f"，provider={result.provider}" if result.provider else ""
        return f"{result.text}\n\n模型狀態：{key_note}，model={result.model}{provider_note}"

    def generate_with_metadata(self, prompt: str) -> LLMResult:
        started_at = monotonic()
        result = self._generate_with_metadata(prompt)
        return self._with_observability(
            prompt=prompt,
            result=result,
            started_at=started_at,
            operation="chat_completion",
        )

    def _generate_with_metadata(self, prompt: str) -> LLMResult:
        prior_attempts: list[dict[str, object]] = []
        if self.provider == "litellm":
            litellm_result = self._generate_with_litellm(prompt)
            if not litellm_result.fallback:
                return litellm_result
            prior_attempts.extend(litellm_result.attempts)
        if self.provider == "google_genai":
            genai_result = self._generate_with_google_genai(prompt)
            if not genai_result.fallback:
                return genai_result
            prior_attempts.extend(genai_result.attempts)

        if len(self.rotator) == 0:
            return _llm_failure_result(
                text=(
                    "目前未設定 LLM API key；已改用規則引擎產生報告草稿。"
                    "接上供應商 SDK 後，仍需保留白名單與來源檢查。"
                ),
                prior_attempts=prior_attempts,
                attempt_record_func=self._attempt_record,
                attempt_provider="gemini_http",
                attempt_model=self.settings.primary_llm_model,
                outcome="missing_api_key",
            )

        return self._generate_with_gemini_http(prompt, prior_attempts=tuple(prior_attempts))

    def generate_structured_with_metadata(
        self,
        prompt: str,
        *,
        tool_schema: dict[str, Any],
        tool_name: str,
    ) -> LLMResult:
        started_at = monotonic()
        if self.provider == "litellm":
            litellm_result = self._generate_with_litellm(
                prompt,
                tools=[tool_schema],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            if not litellm_result.fallback:
                return self._with_observability(
                    prompt=prompt,
                    result=litellm_result,
                    started_at=started_at,
                    operation="structured_completion",
                )
        result = self._generate_with_metadata(prompt)
        return self._with_observability(
            prompt=prompt,
            result=result,
            started_at=started_at,
            operation="structured_completion",
        )

    def generate_vision_with_metadata(
        self,
        prompt: str,
        *,
        images: list[dict[str, Any]],
        model: str | None = None,
    ) -> LLMResult:
        started_at = monotonic()
        result = self._generate_vision_with_metadata(prompt, images=images, model=model)
        trace_prompt = f"{prompt}\n\n[vision_image_count={len(images or [])}]"
        return self._with_observability(
            prompt=trace_prompt,
            result=result,
            started_at=started_at,
            operation="vision_completion",
        )

    def _generate_vision_with_metadata(
        self,
        prompt: str,
        *,
        images: list[dict[str, Any]],
        model: str | None = None,
    ) -> LLMResult:
        normalized_images = self._normalize_vision_images(images)
        if not normalized_images:
            return _llm_failure_result(
                text="Vision completion requires at least one image payload.",
                attempt_record_func=self._attempt_record,
                attempt_provider=self.provider,
                attempt_model=model or self.settings.primary_llm_model,
                outcome="empty_response",
            )

        prior_attempts: list[dict[str, object]] = []
        if self.provider == "litellm":
            litellm_result = self._generate_vision_with_litellm(
                prompt,
                images=normalized_images,
                model=model,
            )
            if not litellm_result.fallback:
                return litellm_result
            prior_attempts.extend(litellm_result.attempts)

        if len(self.rotator) == 0:
            return _llm_failure_result(
                text="Vision LLM API key is not configured; Visual RAG extraction was skipped.",
                prior_attempts=prior_attempts,
                attempt_record_func=self._attempt_record,
                attempt_provider="gemini_http",
                attempt_model=model or self.settings.primary_llm_model,
                outcome="missing_api_key",
            )

        return self._generate_vision_with_gemini_http(
            prompt,
            images=normalized_images,
            model=model,
            prior_attempts=tuple(prior_attempts),
        )

    def _generate_vision_with_litellm(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        model: str | None = None,
    ) -> LLMResult:
        try:
            import_module("litellm")
        except Exception as exc:
            return _llm_failure_result(
                text=f"LiteLLM vision unavailable: {exc.__class__.__name__}",
                provider="litellm",
                attempt_record_func=self._attempt_record,
                attempt_provider="litellm",
                attempt_model=model,
                outcome="dependency_unavailable",
                error=exc.__class__.__name__,
            )

        models = [
            candidate
            for candidate in litellm_model_candidates(self.settings, preferred_model=model)
            if is_vision_model_candidate(candidate)
        ]
        if not models:
            return _llm_failure_result(
                text="LiteLLM vision has no configured model candidates",
                provider="litellm",
                attempt_record_func=self._attempt_record,
                attempt_provider="litellm",
                attempt_model=None,
                outcome="missing_model",
            )

        errors: list[str] = []
        attempts: list[dict[str, object]] = []
        deadline = monotonic() + self.total_timeout_seconds
        use_model_fallback = len(models) > 1
        for plan in self._iter_model_attempt_plans(
            models,
            provider="litellm",
            use_model_fallback=use_model_fallback,
            key_candidates_func=lambda model: litellm_key_candidates(
                model, self.settings, self.rotator
            ),
            max_key_candidates=2,
        ):
            candidate_model = plan.model
            if plan.skipped_attempt:
                attempts.append(plan.skipped_attempt)
                continue
            stop_model_after_quota = False
            for key_index, api_key in plan.key_candidates:
                if stop_model_after_quota:
                    break
                if litellm_model_requires_api_key(candidate_model) and not api_key:
                    attempts.append(
                        self._attempt_record(
                            provider="litellm",
                            model=candidate_model,
                            key_index=key_index,
                            outcome="missing_api_key",
                        )
                    )
                    continue
                if monotonic() >= deadline:
                    errors.append(f"{candidate_model} total timeout before vision attempt")
                    attempts.append(
                        self._attempt_record(
                            provider="litellm",
                            model=candidate_model,
                            key_index=key_index,
                            outcome="timeout",
                        )
                    )
                    break
                try:
                    text = self._call_litellm_vision(
                        prompt,
                        images=images,
                        model=candidate_model,
                        api_key=api_key,
                        timeout_seconds=max(1.0, deadline - monotonic()),
                    )
                    if text:
                        attempts.append(
                            self._attempt_record(
                                provider="litellm",
                                model=candidate_model,
                                key_index=key_index,
                                attempt=1,
                                outcome="success",
                            )
                        )
                        return _llm_success_result(
                            text=text,
                            key_index=key_index,
                            model=candidate_model,
                            provider="litellm",
                            attempts=attempts,
                        )
                    errors.append(f"{candidate_model} empty vision response")
                    attempts.append(
                        self._attempt_record(
                            provider="litellm",
                            model=candidate_model,
                            key_index=key_index,
                            attempt=1,
                            outcome="empty_response",
                        )
                    )
                except Exception as exc:
                    status = self._exception_status_code(exc)
                    errors.append(
                        f"{candidate_model} vision "
                        f"{'HTTP ' + str(status) if status is not None else exc.__class__.__name__}"
                    )
                    if status == 429:
                        self._start_model_quota_cooldown(
                            candidate_model, getattr(exc, "response", None)
                        )
                        stop_model_after_quota = True
                    attempts.append(
                        self._attempt_record(
                            provider="litellm",
                            model=candidate_model,
                            key_index=key_index,
                            attempt=1,
                            outcome="http_error" if status is not None else "provider_error",
                            status=status,
                            error=None if status is not None else exc.__class__.__name__,
                            retryable=_llm_error_retryable(status),
                        )
                    )

        return _llm_failure_result(
            text="LiteLLM vision 呼叫失敗，將改走既有 Gemini HTTP 或略過 Visual RAG。"
            + ("；".join(errors) if errors else ""),
            provider="litellm",
            prior_attempts=attempts,
        )

    def _generate_vision_with_gemini_http(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        model: str | None = None,
        prior_attempts: tuple[dict[str, object], ...] = (),
    ) -> LLMResult:
        errors: list[str] = []
        attempts: list[dict[str, object]] = list(prior_attempts)
        deadline = monotonic() + self.total_timeout_seconds
        model_candidates = gemini_vision_model_candidates(self.settings, preferred_model=model)
        use_model_fallback = len(model_candidates) > 1
        for plan in self._iter_model_attempt_plans(
            model_candidates,
            provider="gemini_http",
            use_model_fallback=use_model_fallback,
            key_candidates_func=lambda _model: self.rotator.candidates(),
        ):
            model_name = plan.model
            if plan.skipped_attempt:
                attempts.append(plan.skipped_attempt)
                continue
            for key_index, api_key in plan.key_candidates:
                if monotonic() >= deadline:
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=model_name,
                            key_index=key_index,
                            outcome="timeout",
                        )
                    )
                    break
                try:
                    text = self._call_gemini_vision(
                        prompt,
                        images=images,
                        api_key=api_key,
                        model=model_name,
                        timeout_seconds=max(1.0, deadline - monotonic()),
                    )
                    if text:
                        attempts.append(
                            self._attempt_record(
                                provider="gemini_http",
                                model=model_name,
                                key_index=key_index,
                                attempt=1,
                                outcome="success",
                            )
                        )
                        return _llm_success_result(
                            text=text,
                            key_index=key_index,
                            model=model_name,
                            provider="gemini_http",
                            attempts=attempts,
                        )
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=model_name,
                            key_index=key_index,
                            attempt=1,
                            outcome="empty_response",
                        )
                    )
                    errors.append(f"{model_name} key[{key_index}] empty vision response")
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status == 429:
                        self._start_model_quota_cooldown(model_name, exc.response)
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=model_name,
                            key_index=key_index,
                            attempt=1,
                            outcome="http_error",
                            status=status,
                            retryable=_llm_error_retryable(status),
                        )
                    )
                    errors.append(f"{model_name} key[{key_index}] vision HTTP {status}")
                    if _llm_should_stop_after_status(
                        status,
                        use_model_fallback=use_model_fallback,
                    ):
                        break
                except httpx.HTTPError as exc:
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=model_name,
                            key_index=key_index,
                            attempt=1,
                            outcome="transport_error",
                            error=exc.__class__.__name__,
                            retryable=True,
                        )
                    )
                    errors.append(f"{model_name} key[{key_index}] vision {exc.__class__.__name__}")

        return _llm_failure_result(
            text="Gemini vision 呼叫失敗，Visual RAG 未產生可用文字。"
            + ("；".join(errors) if errors else ""),
            prior_attempts=attempts,
        )

    @staticmethod
    def _attempt_record(
        *,
        provider: str,
        model: str | None,
        outcome: str,
        key_index: int | None = None,
        attempt: int | None = None,
        status: int | None = None,
        error: str | None = None,
        retryable: bool | None = None,
        cooldown_seconds: float | None = None,
    ) -> dict[str, object]:
        return _llm_attempt_record(
            provider=provider,
            model=model,
            outcome=outcome,
            key_index=key_index,
            attempt=attempt,
            status=status,
            error=error,
            retryable=retryable,
            cooldown_seconds=cooldown_seconds,
        )

    def _sleep_before_retry(self, response: Optional[httpx.Response], attempt: int) -> None:
        sleep(self._retry_delay_seconds(response, attempt))

    def _retry_delay_seconds(self, response: Optional[httpx.Response], attempt: int) -> float:
        return _llm_retry_delay_seconds(
            response,
            attempt,
            base_retry_delay_seconds=self.base_retry_delay_seconds,
            max_retry_delay_seconds=self.max_retry_delay_seconds,
        )

    @property
    def provider(self) -> str:
        return (
            str(getattr(self.settings, "llm_provider", "gemini_http") or "gemini_http")
            .lower()
            .replace("-", "_")
        )

    @property
    def max_retries_per_key(self) -> int:
        return max(
            0, int(getattr(self.settings, "llm_max_retries_per_key", DEFAULT_MAX_RETRIES_PER_KEY))
        )

    @property
    def base_retry_delay_seconds(self) -> float:
        return max(
            0.0,
            float(
                getattr(
                    self.settings, "llm_base_retry_delay_seconds", DEFAULT_BASE_RETRY_DELAY_SECONDS
                )
            ),
        )

    @property
    def max_retry_delay_seconds(self) -> float:
        return max(
            0.0,
            float(
                getattr(
                    self.settings, "llm_max_retry_delay_seconds", DEFAULT_MAX_RETRY_DELAY_SECONDS
                )
            ),
        )

    @property
    def total_timeout_seconds(self) -> float:
        return max(
            1.0,
            float(
                getattr(self.settings, "llm_total_timeout_seconds", DEFAULT_TOTAL_TIMEOUT_SECONDS)
            ),
        )

    @staticmethod
    def _quota_governance_service_cls() -> type[LLMQuotaGovernanceService]:
        return LLMQuotaGovernanceService

    def healthcheck(self) -> LLMResult:
        return self.generate_with_metadata("請只回答 ok，不要輸出任何其他文字。")

    def _with_observability(
        self,
        *,
        prompt: str,
        result: LLMResult,
        started_at: float,
        operation: str,
    ) -> LLMResult:
        return _attach_llm_observability(
            prompt=prompt,
            result=result,
            started_at=started_at,
            operation=operation,
            settings=self.settings,
        )

    @staticmethod
    def _import_module(name: str) -> object:
        return import_module(name)
