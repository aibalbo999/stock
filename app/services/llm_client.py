from __future__ import annotations

from importlib import import_module
from time import monotonic, sleep
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.services.api_key_rotation import APIKeyRotator, get_shared_rotator
from app.services.llm_attempt_planning import iter_model_attempt_plans
from app.services.llm_attempts import llm_attempt_failure_category, summarize_llm_attempts
from app.services.llm_models import (
    gemini_model_candidates,
    gemini_vision_model_candidates,
    is_vision_model_candidate,
    litellm_key_candidates,
    litellm_model_candidates,
    litellm_model_requires_api_key,
)
from app.services.llm_observability import (
    build_llm_observability_trace,
    dispatch_llm_observability_trace,
)
from app.services.llm_provider_calls import (
    call_gemini as _call_gemini_provider,
    call_gemini_vision as _call_gemini_vision_provider,
    call_google_genai as _call_google_genai_provider,
    call_litellm as _call_litellm_provider,
    call_litellm_vision as _call_litellm_vision_provider,
    google_genai_response_text as _google_genai_response_text_provider,
    image_data_url as _image_data_url_provider,
    normalize_vision_images as _normalize_vision_images_provider,
    tool_call_arguments as _tool_call_arguments_provider,
)
from app.services.llm_runtime import (
    DEFAULT_BASE_RETRY_DELAY_SECONDS,
    DEFAULT_MAX_RETRIES_PER_KEY,
    DEFAULT_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_MODEL_QUOTA_COOLDOWN_SECONDS,
    DEFAULT_TOTAL_TIMEOUT_SECONDS,
    LLMResult,
    RETRYABLE_HTTP_STATUSES,
    ROTATABLE_HTTP_STATUSES,
    _model_quota_cooldowns as _model_quota_cooldowns,
    _model_quota_cooldowns_lock as _model_quota_cooldowns_lock,
    daily_quota_exhausted_model_keys as _runtime_daily_quota_exhausted_model_keys,
    exception_status_code as _exception_status_code,
    llm_attempt_record as _llm_attempt_record,
    llm_retry_delay_seconds as _llm_retry_delay_seconds,
    model_daily_quota_exhausted as _runtime_model_daily_quota_exhausted,
    model_quota_cooldown_remaining as _runtime_model_quota_cooldown_remaining,
    start_model_quota_cooldown as _runtime_start_model_quota_cooldown,
)

__all__ = [
    "APIKeyRotator",
    "LLMClient",
    "LLMResult",
    "get_shared_rotator",
    "llm_attempt_failure_category",
    "summarize_llm_attempts",
]


class LLMClient:
    """Provider boundary for Gemini/Gemma analysis.

    The MVP keeps this adapter deliberately thin. In production, put provider-specific
    SDK calls here and keep prompts, evidence, and whitelist checks outside the model.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.rotator = get_shared_rotator(self.settings.gemini_api_keys)

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
            return LLMResult(
                text=(
                    "目前未設定 LLM API key；已改用規則引擎產生報告草稿。"
                    "接上供應商 SDK 後，仍需保留白名單與來源檢查。"
                ),
                fallback=True,
                attempts=tuple(
                    [
                        *prior_attempts,
                        self._attempt_record(
                            provider="gemini_http",
                            model=self.settings.primary_llm_model,
                            outcome="missing_api_key",
                        ),
                    ]
                ),
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
            return LLMResult(
                text="Vision completion requires at least one image payload.",
                fallback=True,
                attempts=(
                    self._attempt_record(
                        provider=self.provider,
                        model=model or self.settings.primary_llm_model,
                        outcome="empty_response",
                    ),
                ),
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
            return LLMResult(
                text="Vision LLM API key is not configured; Visual RAG extraction was skipped.",
                fallback=True,
                attempts=tuple(
                    [
                        *prior_attempts,
                        self._attempt_record(
                            provider="gemini_http",
                            model=model or self.settings.primary_llm_model,
                            outcome="missing_api_key",
                        ),
                    ]
                ),
            )

        return self._generate_vision_with_gemini_http(
            prompt,
            images=normalized_images,
            model=model,
            prior_attempts=tuple(prior_attempts),
        )

    def _generate_with_gemini_http(
        self,
        prompt: str,
        prior_attempts: tuple[dict[str, object], ...] = (),
    ) -> LLMResult:
        errors: list[str] = []
        attempts: list[dict[str, object]] = list(prior_attempts)
        deadline = monotonic() + self.total_timeout_seconds
        models = gemini_model_candidates(self.settings)
        use_model_fallback = len(models) > 1
        for plan in self._iter_model_attempt_plans(
            models,
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
                    errors.append(f"{model_name} total timeout before trying next key")
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=model_name,
                            key_index=key_index,
                            outcome="timeout",
                        )
                    )
                    break
                should_stop = False
                max_retries = 0 if use_model_fallback else self.max_retries_per_key
                for attempt in range(max_retries + 1):
                    if monotonic() >= deadline:
                        errors.append(
                            f"{model_name} key[{key_index}] total timeout before attempt {attempt + 1}"
                        )
                        attempts.append(
                            self._attempt_record(
                                provider="gemini_http",
                                model=model_name,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="timeout",
                            )
                        )
                        should_stop = True
                        break
                    try:
                        text = self._call_gemini(
                            prompt,
                            api_key,
                            model=model_name,
                            timeout_seconds=max(1.0, deadline - monotonic()),
                        )
                        if text:
                            attempts.append(
                                self._attempt_record(
                                    provider="gemini_http",
                                    model=model_name,
                                    key_index=key_index,
                                    attempt=attempt + 1,
                                    outcome="success",
                                )
                            )
                            return LLMResult(
                                text=text,
                                key_index=key_index,
                                model=model_name,
                                provider="gemini_http",
                                attempts=tuple(attempts),
                            )
                        errors.append(f"{model_name} key[{key_index}] empty response")
                        attempts.append(
                            self._attempt_record(
                                provider="gemini_http",
                                model=model_name,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="empty_response",
                            )
                        )
                        break
                    except httpx.HTTPStatusError as exc:
                        status = exc.response.status_code
                        errors.append(
                            f"{model_name} key[{key_index}] HTTP {status} attempt {attempt + 1}"
                        )
                        if status == 429:
                            self._start_model_quota_cooldown(model_name, exc.response)
                        attempts.append(
                            self._attempt_record(
                                provider="gemini_http",
                                model=model_name,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="http_error",
                                status=status,
                                retryable=status in RETRYABLE_HTTP_STATUSES,
                            )
                        )
                        if status not in ROTATABLE_HTTP_STATUSES:
                            should_stop = True
                            break
                        if status == 429 and use_model_fallback:
                            should_stop = True
                            break
                        if (
                            status in RETRYABLE_HTTP_STATUSES
                            and attempt < max_retries
                            and monotonic() < deadline
                        ):
                            self._sleep_before_retry(exc.response, attempt)
                            continue
                        break
                    except httpx.HTTPError as exc:
                        errors.append(
                            f"{model_name} key[{key_index}] {exc.__class__.__name__} attempt {attempt + 1}"
                        )
                        attempts.append(
                            self._attempt_record(
                                provider="gemini_http",
                                model=model_name,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="transport_error",
                                error=exc.__class__.__name__,
                                retryable=True,
                            )
                        )
                        if attempt < max_retries and monotonic() < deadline:
                            self._sleep_before_retry(None, attempt)
                            continue
                        break
                if should_stop:
                    break

        return LLMResult(
            text=(
                "LLM 呼叫失敗，已改用規則引擎產生報告草稿。"
                f"輪調嘗試：{'; '.join(errors) if errors else '無'}"
            ),
            fallback=True,
            attempts=tuple(attempts),
        )

    def _generate_with_google_genai(self, prompt: str) -> LLMResult:
        try:
            import_module("google.genai")
        except Exception as exc:
            return LLMResult(
                text=f"Google GenAI SDK unavailable: {exc.__class__.__name__}",
                provider="google_genai",
                fallback=True,
                attempts=(
                    self._attempt_record(
                        provider="google_genai",
                        model=self.settings.primary_llm_model,
                        outcome="dependency_unavailable",
                        error=exc.__class__.__name__,
                    ),
                ),
            )

        if len(self.rotator) == 0:
            return LLMResult(
                text="Google GenAI SDK has no configured API key",
                provider="google_genai",
                fallback=True,
                attempts=(
                    self._attempt_record(
                        provider="google_genai",
                        model=self.settings.primary_llm_model,
                        outcome="missing_api_key",
                    ),
                ),
            )

        errors: list[str] = []
        attempts: list[dict[str, object]] = []
        deadline = monotonic() + self.total_timeout_seconds
        models = gemini_model_candidates(self.settings)
        use_model_fallback = len(models) > 1
        for plan in self._iter_model_attempt_plans(
            models,
            provider="google_genai",
            use_model_fallback=use_model_fallback,
            key_candidates_func=lambda _model: self.rotator.candidates(),
        ):
            model_name = plan.model
            if plan.skipped_attempt:
                attempts.append(plan.skipped_attempt)
                continue
            for key_index, api_key in plan.key_candidates:
                max_retries = 0 if use_model_fallback else self.max_retries_per_key
                should_stop = False
                for attempt in range(max_retries + 1):
                    if monotonic() >= deadline:
                        errors.append(
                            f"{model_name} key[{key_index}] total timeout before SDK attempt {attempt + 1}"
                        )
                        attempts.append(
                            self._attempt_record(
                                provider="google_genai",
                                model=model_name,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="timeout",
                            )
                        )
                        should_stop = True
                        break
                    try:
                        text = self._call_google_genai(
                            prompt,
                            api_key,
                            model=model_name,
                            timeout_seconds=max(1.0, deadline - monotonic()),
                        )
                        if text:
                            attempts.append(
                                self._attempt_record(
                                    provider="google_genai",
                                    model=model_name,
                                    key_index=key_index,
                                    attempt=attempt + 1,
                                    outcome="success",
                                )
                            )
                            return LLMResult(
                                text=text,
                                key_index=key_index,
                                model=model_name,
                                provider="google_genai",
                                attempts=tuple(attempts),
                            )
                        errors.append(f"{model_name} key[{key_index}] empty SDK response")
                        attempts.append(
                            self._attempt_record(
                                provider="google_genai",
                                model=model_name,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="empty_response",
                            )
                        )
                        break
                    except Exception as exc:
                        status = self._exception_status_code(exc)
                        status_label = (
                            f"HTTP {status}" if status is not None else exc.__class__.__name__
                        )
                        errors.append(
                            f"{model_name} key[{key_index}] SDK {status_label} attempt {attempt + 1}"
                        )
                        if status == 429:
                            self._start_model_quota_cooldown(
                                model_name, getattr(exc, "response", None)
                            )
                        attempts.append(
                            self._attempt_record(
                                provider="google_genai",
                                model=model_name,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="http_error" if status is not None else "sdk_error",
                                status=status,
                                error=None if status is not None else exc.__class__.__name__,
                                retryable=(status in RETRYABLE_HTTP_STATUSES)
                                if status is not None
                                else True,
                            )
                        )
                        if status is not None and status not in ROTATABLE_HTTP_STATUSES:
                            should_stop = True
                            break
                        if status == 429 and use_model_fallback:
                            should_stop = True
                            break
                        if attempt < max_retries and monotonic() < deadline:
                            self._sleep_before_retry(getattr(exc, "response", None), attempt)
                            continue
                        break
                if should_stop:
                    break

        return LLMResult(
            text="Google GenAI SDK 呼叫失敗，將改走既有 Gemini HTTP 或規則引擎。"
            + ("；".join(errors) if errors else ""),
            provider="google_genai",
            fallback=True,
            attempts=tuple(attempts),
        )

    def _generate_with_litellm(
        self,
        prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
    ) -> LLMResult:
        try:
            import_module("litellm")
        except Exception as exc:
            return LLMResult(
                text=f"LiteLLM unavailable: {exc.__class__.__name__}",
                provider="litellm",
                fallback=True,
                attempts=(
                    self._attempt_record(
                        provider="litellm",
                        model=None,
                        outcome="dependency_unavailable",
                        error=exc.__class__.__name__,
                    ),
                ),
            )

        models = litellm_model_candidates(self.settings)
        if not models:
            return LLMResult(
                text="LiteLLM has no configured model candidates",
                provider="litellm",
                fallback=True,
                attempts=(
                    self._attempt_record(
                        provider="litellm",
                        model=None,
                        outcome="missing_model",
                    ),
                ),
            )

        errors: list[str] = []
        attempts: list[dict[str, object]] = []
        deadline = monotonic() + self.total_timeout_seconds
        use_fast_model_chain_fallback = len(models) > 1
        for plan in self._iter_model_attempt_plans(
            models,
            provider="litellm",
            use_model_fallback=use_fast_model_chain_fallback,
            key_candidates_func=lambda model: litellm_key_candidates(
                model, self.settings, self.rotator
            ),
        ):
            model = plan.model
            if plan.skipped_attempt:
                attempts.append(plan.skipped_attempt)
                continue
            stop_model_after_quota = False
            for key_index, api_key in plan.key_candidates:
                if stop_model_after_quota:
                    break
                if litellm_model_requires_api_key(model) and not api_key:
                    attempts.append(
                        self._attempt_record(
                            provider="litellm",
                            model=model,
                            key_index=key_index,
                            outcome="missing_api_key",
                        )
                    )
                    continue
                max_retries = self.max_retries_per_key
                if use_fast_model_chain_fallback:
                    max_retries = 0
                for attempt in range(max_retries + 1):
                    if monotonic() >= deadline:
                        errors.append(f"{model} total timeout before attempt {attempt + 1}")
                        attempts.append(
                            self._attempt_record(
                                provider="litellm",
                                model=model,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="timeout",
                            )
                        )
                        break
                    try:
                        text = self._call_litellm(
                            prompt,
                            model,
                            api_key=api_key,
                            timeout_seconds=max(1.0, deadline - monotonic()),
                            tools=tools,
                            tool_choice=tool_choice,
                        )
                        if text:
                            attempts.append(
                                self._attempt_record(
                                    provider="litellm",
                                    model=model,
                                    key_index=key_index,
                                    attempt=attempt + 1,
                                    outcome="success",
                                )
                            )
                            return LLMResult(
                                text=text,
                                key_index=key_index,
                                model=model,
                                provider="litellm",
                                attempts=tuple(attempts),
                            )
                        errors.append(f"{model} empty response")
                        attempts.append(
                            self._attempt_record(
                                provider="litellm",
                                model=model,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="empty_response",
                            )
                        )
                        break
                    except Exception as exc:
                        status = self._exception_status_code(exc)
                        status_label = (
                            f"HTTP {status}" if status is not None else exc.__class__.__name__
                        )
                        errors.append(
                            f"{model} key[{key_index}] {status_label} attempt {attempt + 1}"
                        )
                        if status == 429:
                            self._start_model_quota_cooldown(model, getattr(exc, "response", None))
                        attempts.append(
                            self._attempt_record(
                                provider="litellm",
                                model=model,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="http_error" if status is not None else "provider_error",
                                status=status,
                                error=None if status is not None else exc.__class__.__name__,
                                retryable=(status in RETRYABLE_HTTP_STATUSES)
                                if status is not None
                                else True,
                            )
                        )
                        if status is not None and status not in ROTATABLE_HTTP_STATUSES:
                            break
                        if status == 429 and use_fast_model_chain_fallback:
                            stop_model_after_quota = True
                            break
                        if attempt < max_retries and monotonic() < deadline:
                            self._sleep_before_retry(getattr(exc, "response", None), attempt)
                            continue
                        break

        return LLMResult(
            text="LiteLLM 呼叫失敗，將改走既有 Gemini HTTP 或規則引擎。"
            + ("；".join(errors) if errors else ""),
            provider="litellm",
            fallback=True,
            attempts=tuple(attempts),
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
            return LLMResult(
                text=f"LiteLLM vision unavailable: {exc.__class__.__name__}",
                provider="litellm",
                fallback=True,
                attempts=(
                    self._attempt_record(
                        provider="litellm",
                        model=model,
                        outcome="dependency_unavailable",
                        error=exc.__class__.__name__,
                    ),
                ),
            )

        models = [
            candidate
            for candidate in litellm_model_candidates(self.settings, preferred_model=model)
            if is_vision_model_candidate(candidate)
        ]
        if not models:
            return LLMResult(
                text="LiteLLM vision has no configured model candidates",
                provider="litellm",
                fallback=True,
                attempts=(
                    self._attempt_record(
                        provider="litellm",
                        model=None,
                        outcome="missing_model",
                    ),
                ),
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
                        return LLMResult(
                            text=text,
                            key_index=key_index,
                            model=candidate_model,
                            provider="litellm",
                            attempts=tuple(attempts),
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
                            retryable=(status in RETRYABLE_HTTP_STATUSES)
                            if status is not None
                            else True,
                        )
                    )

        return LLMResult(
            text="LiteLLM vision 呼叫失敗，將改走既有 Gemini HTTP 或略過 Visual RAG。"
            + ("；".join(errors) if errors else ""),
            provider="litellm",
            fallback=True,
            attempts=tuple(attempts),
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
                        return LLMResult(
                            text=text,
                            key_index=key_index,
                            model=model_name,
                            provider="gemini_http",
                            attempts=tuple(attempts),
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
                            retryable=status in RETRYABLE_HTTP_STATUSES,
                        )
                    )
                    errors.append(f"{model_name} key[{key_index}] vision HTTP {status}")
                    if status is not None and status not in ROTATABLE_HTTP_STATUSES:
                        break
                    if status == 429 and use_model_fallback:
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

        return LLMResult(
            text="Gemini vision 呼叫失敗，Visual RAG 未產生可用文字。"
            + ("；".join(errors) if errors else ""),
            fallback=True,
            attempts=tuple(attempts),
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

    @property
    def model_quota_cooldown_seconds(self) -> float:
        return max(
            0.0,
            float(
                getattr(
                    self.settings,
                    "llm_model_quota_cooldown_seconds",
                    DEFAULT_MODEL_QUOTA_COOLDOWN_SECONDS,
                )
            ),
        )

    def _model_quota_cooldown_remaining(self, model: str) -> float:
        return _runtime_model_quota_cooldown_remaining(model)

    def _start_model_quota_cooldown(
        self,
        model: str,
        response: Optional[httpx.Response],
    ) -> None:
        cooldown_seconds = self._retry_delay_seconds(response, 0) if response is not None else 0.0
        if cooldown_seconds <= 0 or cooldown_seconds == self.base_retry_delay_seconds:
            cooldown_seconds = self.model_quota_cooldown_seconds
        if cooldown_seconds <= 0:
            return
        _runtime_start_model_quota_cooldown(model, cooldown_seconds)

    def _daily_quota_exhausted_model_keys(self) -> set[str]:
        return _runtime_daily_quota_exhausted_model_keys(self.settings)

    @staticmethod
    def _model_daily_quota_exhausted(model: str, exhausted_model_keys: set[str]) -> bool:
        return _runtime_model_daily_quota_exhausted(model, exhausted_model_keys)

    def _iter_model_attempt_plans(
        self,
        models: list[str],
        *,
        provider: str,
        use_model_fallback: bool,
        key_candidates_func,
        max_key_candidates: int | None = None,
    ):
        return iter_model_attempt_plans(
            models,
            provider=provider,
            daily_exhausted_model_keys=self._daily_quota_exhausted_model_keys(),
            cooldown_remaining_func=self._model_quota_cooldown_remaining,
            key_candidates_func=key_candidates_func,
            attempt_record_func=self._attempt_record,
            use_model_fallback=use_model_fallback,
            max_key_candidates=max_key_candidates,
        )

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
        observability = build_llm_observability_trace(
            prompt=prompt,
            result=result,
            latency_ms=(monotonic() - started_at) * 1000,
            operation=operation,
            settings=self.settings,
        )
        observability["external_trace_dispatch"] = dispatch_llm_observability_trace(
            observability,
            prompt=prompt,
            output=result.text,
            settings=self.settings,
        )
        return LLMResult(
            text=result.text,
            key_index=result.key_index,
            model=result.model,
            provider=result.provider,
            fallback=result.fallback,
            attempts=result.attempts,
            observability=observability,
        )

    @staticmethod
    def _exception_status_code(exc: Exception) -> int | None:
        return _exception_status_code(exc)

    def _call_litellm(
        self,
        prompt: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
    ) -> str:
        return _call_litellm_provider(
            prompt,
            model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            tools=tools,
            tool_choice=tool_choice,
            import_module_func=import_module,
        )

    def _call_litellm_vision(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        model: str,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_litellm_vision_provider(
            prompt,
            images=images,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            import_module_func=import_module,
        )

    @staticmethod
    def _tool_call_arguments(message: object) -> str:
        return _tool_call_arguments_provider(message)

    def _call_google_genai(
        self,
        prompt: str,
        api_key: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_google_genai_provider(
            prompt,
            api_key,
            model=model,
            primary_model=self.settings.primary_llm_model,
            timeout_seconds=timeout_seconds,
            import_module_func=import_module,
        )

    @staticmethod
    def _google_genai_response_text(response: object) -> str:
        return _google_genai_response_text_provider(response)

    def _call_gemini(
        self,
        prompt: str,
        api_key: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_gemini_provider(
            prompt,
            api_key,
            model=model,
            primary_model=self.settings.primary_llm_model,
            timeout_seconds=timeout_seconds,
        )

    def _call_gemini_vision(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        api_key: str,
        model: str,
        timeout_seconds: float | None = None,
    ) -> str:
        return _call_gemini_vision_provider(
            prompt,
            images=images,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _normalize_vision_images(images: list[dict[str, Any]]) -> list[dict[str, str]]:
        return _normalize_vision_images_provider(images)

    @staticmethod
    def _image_data_url(image: dict[str, str]) -> str:
        return _image_data_url_provider(image)
