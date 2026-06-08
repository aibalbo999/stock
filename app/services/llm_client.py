from __future__ import annotations

import base64
from dataclasses import dataclass, field
from importlib import import_module
from threading import Lock
from time import monotonic, sleep
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.services.api_key_rotation import APIKeyRotator, get_shared_rotator
from app.services.llm_attempts import llm_attempt_failure_category, summarize_llm_attempts
from app.services.llm_quota import LLMQuotaGovernanceService, normalize_model_name
from app.services.llm_observability import (
    build_llm_observability_trace,
    dispatch_llm_observability_trace,
)

__all__ = [
    "APIKeyRotator",
    "LLMClient",
    "LLMResult",
    "get_shared_rotator",
    "llm_attempt_failure_category",
    "summarize_llm_attempts",
]

RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
ROTATABLE_HTTP_STATUSES = {401, 403, *RETRYABLE_HTTP_STATUSES}
DEFAULT_MAX_RETRIES_PER_KEY = 1
DEFAULT_BASE_RETRY_DELAY_SECONDS = 0.5
DEFAULT_MAX_RETRY_DELAY_SECONDS = 5.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0
DEFAULT_MODEL_QUOTA_COOLDOWN_SECONDS = 60 * 60


@dataclass(frozen=True)
class LLMResult:
    text: str
    key_index: int | None = None
    model: str | None = None
    provider: str | None = None
    fallback: bool = False
    attempts: tuple[dict[str, object], ...] = field(default_factory=tuple)
    observability: dict[str, object] = field(default_factory=dict)


_model_quota_cooldowns: dict[str, float] = {}
_model_quota_cooldowns_lock = Lock()


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
        models = self._gemini_model_candidates()
        use_model_fallback = len(models) > 1
        daily_exhausted = self._daily_quota_exhausted_model_keys()
        for model_name in models:
            if self._model_daily_quota_exhausted(model_name, daily_exhausted):
                attempts.append(
                    self._attempt_record(
                        provider="gemini_http",
                        model=model_name,
                        outcome="quota_daily_exhausted",
                        retryable=True,
                    )
                )
                continue
            if use_model_fallback:
                cooldown_remaining = self._model_quota_cooldown_remaining(model_name)
                if cooldown_remaining > 0:
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=model_name,
                            outcome="quota_cooldown",
                            retryable=True,
                            cooldown_seconds=cooldown_remaining,
                        )
                    )
                    continue
            key_candidates = self.rotator.candidates()
            if use_model_fallback and len(key_candidates) > 2:
                key_candidates = key_candidates[:2]
            for key_index, api_key in key_candidates:
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
        models = self._gemini_model_candidates()
        use_model_fallback = len(models) > 1
        daily_exhausted = self._daily_quota_exhausted_model_keys()
        for model_name in models:
            if self._model_daily_quota_exhausted(model_name, daily_exhausted):
                attempts.append(
                    self._attempt_record(
                        provider="google_genai",
                        model=model_name,
                        outcome="quota_daily_exhausted",
                        retryable=True,
                    )
                )
                continue
            if use_model_fallback:
                cooldown_remaining = self._model_quota_cooldown_remaining(model_name)
                if cooldown_remaining > 0:
                    attempts.append(
                        self._attempt_record(
                            provider="google_genai",
                            model=model_name,
                            outcome="quota_cooldown",
                            retryable=True,
                            cooldown_seconds=cooldown_remaining,
                        )
                    )
                    continue
            key_candidates = self.rotator.candidates()
            if use_model_fallback and len(key_candidates) > 2:
                key_candidates = key_candidates[:2]
            for key_index, api_key in key_candidates:
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

        models = self._litellm_model_candidates()
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
        daily_exhausted = self._daily_quota_exhausted_model_keys()
        for model in models:
            stop_model_after_quota = False
            if self._model_daily_quota_exhausted(model, daily_exhausted):
                attempts.append(
                    self._attempt_record(
                        provider="litellm",
                        model=model,
                        outcome="quota_daily_exhausted",
                        retryable=True,
                    )
                )
                continue
            if use_fast_model_chain_fallback:
                cooldown_remaining = self._model_quota_cooldown_remaining(model)
                if cooldown_remaining > 0:
                    attempts.append(
                        self._attempt_record(
                            provider="litellm",
                            model=model,
                            outcome="quota_cooldown",
                            retryable=True,
                            cooldown_seconds=cooldown_remaining,
                        )
                    )
                    continue
            key_candidates = self._litellm_key_candidates(model)
            if use_fast_model_chain_fallback and len(key_candidates) > 2:
                key_candidates = key_candidates[:2]
            for key_index, api_key in key_candidates:
                if stop_model_after_quota:
                    break
                if self._litellm_model_requires_api_key(model) and not api_key:
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
            for candidate in self._litellm_model_candidates(preferred_model=model)
            if self._is_vision_model_candidate(candidate)
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
        daily_exhausted = self._daily_quota_exhausted_model_keys()
        for candidate_model in models:
            stop_model_after_quota = False
            if self._model_daily_quota_exhausted(candidate_model, daily_exhausted):
                attempts.append(
                    self._attempt_record(
                        provider="litellm",
                        model=candidate_model,
                        outcome="quota_daily_exhausted",
                        retryable=True,
                    )
                )
                continue
            if use_model_fallback:
                cooldown_remaining = self._model_quota_cooldown_remaining(candidate_model)
                if cooldown_remaining > 0:
                    attempts.append(
                        self._attempt_record(
                            provider="litellm",
                            model=candidate_model,
                            outcome="quota_cooldown",
                            retryable=True,
                            cooldown_seconds=cooldown_remaining,
                        )
                    )
                    continue
            key_candidates = self._litellm_key_candidates(candidate_model)
            for key_index, api_key in key_candidates[:2]:
                if stop_model_after_quota:
                    break
                if self._litellm_model_requires_api_key(candidate_model) and not api_key:
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
        model_candidates = self._gemini_vision_model_candidates(preferred_model=model)
        use_model_fallback = len(model_candidates) > 1
        daily_exhausted = self._daily_quota_exhausted_model_keys()
        for model_name in model_candidates:
            if self._model_daily_quota_exhausted(model_name, daily_exhausted):
                attempts.append(
                    self._attempt_record(
                        provider="gemini_http",
                        model=model_name,
                        outcome="quota_daily_exhausted",
                        retryable=True,
                    )
                )
                continue
            if use_model_fallback:
                cooldown_remaining = self._model_quota_cooldown_remaining(model_name)
                if cooldown_remaining > 0:
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=model_name,
                            outcome="quota_cooldown",
                            retryable=True,
                            cooldown_seconds=cooldown_remaining,
                        )
                    )
                    continue
            key_candidates = self.rotator.candidates()
            if len(model_candidates) > 1 and len(key_candidates) > 2:
                key_candidates = key_candidates[:2]
            for key_index, api_key in key_candidates:
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
        record: dict[str, object] = {
            "provider": provider,
            "outcome": outcome,
        }
        if model:
            record["model"] = model
        if key_index is not None:
            record["key_index"] = key_index
        if attempt is not None:
            record["attempt"] = attempt
        if status is not None:
            record["status"] = int(status)
        if error:
            record["error"] = error
        if retryable is not None:
            record["retryable"] = bool(retryable)
        if cooldown_seconds is not None:
            record["cooldown_seconds"] = round(max(0.0, float(cooldown_seconds)), 3)
        return record

    def _sleep_before_retry(self, response: Optional[httpx.Response], attempt: int) -> None:
        sleep(self._retry_delay_seconds(response, attempt))

    def _retry_delay_seconds(self, response: Optional[httpx.Response], attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(self.max_retry_delay_seconds, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        return min(self.max_retry_delay_seconds, self.base_retry_delay_seconds * (2**attempt))

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
        key = self._model_quota_cooldown_key(model)
        now = monotonic()
        with _model_quota_cooldowns_lock:
            until = _model_quota_cooldowns.get(key, 0.0)
            if until <= now:
                _model_quota_cooldowns.pop(key, None)
                return 0.0
            return until - now

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
        key = self._model_quota_cooldown_key(model)
        until = monotonic() + cooldown_seconds
        with _model_quota_cooldowns_lock:
            _model_quota_cooldowns[key] = max(_model_quota_cooldowns.get(key, 0.0), until)

    def _daily_quota_exhausted_model_keys(self) -> set[str]:
        if not bool(getattr(self.settings, "llm_quota_hard_routing_enabled", True)):
            return set()
        try:
            return LLMQuotaGovernanceService(
                settings_provider=lambda: self.settings
            ).exhausted_model_keys()
        except Exception:
            return set()

    @staticmethod
    def _model_daily_quota_exhausted(model: str, exhausted_model_keys: set[str]) -> bool:
        return normalize_model_name(model) in exhausted_model_keys

    @staticmethod
    def _model_quota_cooldown_key(model: str) -> str:
        normalized = str(model or "").strip().lower()
        if normalized.startswith("models/"):
            normalized = normalized.removeprefix("models/")
        if normalized.startswith("gemini/"):
            normalized = normalized.removeprefix("gemini/")
        return normalized

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

    def _litellm_model_candidates(self, preferred_model: str | None = None) -> list[str]:
        models = [self._litellm_model_name(preferred_model or self.settings.primary_llm_model)]
        raw_fallbacks = str(getattr(self.settings, "llm_fallback_models", "") or "")
        models.extend(
            self._litellm_model_name(model.strip())
            for model in raw_fallbacks.split(",")
            if model.strip()
        )
        local_model = str(getattr(self.settings, "local_llm_model", "") or "").strip()
        if local_model:
            models.append(self._litellm_model_name(local_model))
        return list(dict.fromkeys(model for model in models if model))

    def _gemini_model_candidates(self, preferred_model: str | None = None) -> list[str]:
        models = [self._gemini_api_model_name(preferred_model or self.settings.primary_llm_model)]
        raw_fallbacks = str(getattr(self.settings, "llm_fallback_models", "") or "")
        models.extend(
            self._gemini_api_model_name(model.strip())
            for model in raw_fallbacks.split(",")
            if model.strip()
        )
        local_model = str(getattr(self.settings, "local_llm_model", "") or "").strip()
        if local_model:
            models.append(self._gemini_api_model_name(local_model))
        return list(
            dict.fromkeys(
                model for model in models if model and self._is_gemini_text_model_candidate(model)
            )
        )

    def _gemini_vision_model_candidates(self, preferred_model: str | None = None) -> list[str]:
        return [
            model
            for model in self._gemini_model_candidates(preferred_model=preferred_model)
            if self._is_vision_model_candidate(model)
        ]

    @staticmethod
    def _gemini_api_model_name(model: str | None) -> str:
        normalized = str(model or "").strip()
        if normalized.startswith("models/"):
            normalized = normalized.removeprefix("models/")
        if normalized.startswith("gemini/"):
            normalized = normalized.removeprefix("gemini/")
        return normalized

    @staticmethod
    def _is_gemini_text_model_candidate(model: str) -> bool:
        normalized = str(model or "").strip().lower()
        if not normalized.startswith(("gemini", "gemma")):
            return False
        return not any(
            blocked in normalized
            for blocked in ("embedding", "imagen", "image", "live", "tts", "audio")
        )

    @staticmethod
    def _is_vision_model_candidate(model: str) -> bool:
        normalized = str(model or "").strip().lower()
        if normalized.startswith(("models/", "gemini/")):
            normalized = normalized.split("/", 1)[1]
        if normalized.startswith("gemma"):
            return False
        return (
            normalized.startswith("gemini")
            or normalized.startswith("gpt-")
            or normalized.startswith("openai/")
            or normalized.startswith("claude")
            or normalized.startswith("anthropic/")
        ) and not any(
            blocked in normalized
            for blocked in ("embedding", "imagen", "image", "live", "tts", "audio")
        )

    @staticmethod
    def _litellm_model_name(model: str) -> str:
        normalized = str(model or "").strip()
        if not normalized or "/" in normalized:
            return normalized
        if normalized.startswith(("gemini", "gemma")):
            return f"gemini/{normalized}"
        if normalized.startswith("claude"):
            return f"anthropic/{normalized}"
        return normalized

    def _litellm_key_candidates(self, model: str) -> list[tuple[int | None, str | None]]:
        normalized = str(model or "").strip().lower()
        if (normalized.startswith("gemini/") or normalized.startswith("gemma")) and len(
            self.rotator
        ) > 0:
            return self.rotator.candidates()
        if normalized.startswith("openai/") or normalized.startswith("gpt-"):
            api_key = getattr(self.settings, "openai_api_key", None)
            return [(None, api_key)] if api_key else [(None, None)]
        if normalized.startswith("anthropic/") or normalized.startswith("claude"):
            api_key = getattr(self.settings, "anthropic_api_key", None)
            return [(None, api_key)] if api_key else [(None, None)]
        return [(None, None)]

    @staticmethod
    def _litellm_model_requires_api_key(model: str) -> bool:
        normalized = str(model or "").strip().lower()
        return (
            normalized.startswith("gemini/")
            or normalized.startswith("gemma")
            or normalized.startswith("openai/")
            or normalized.startswith("gpt-")
            or normalized.startswith("anthropic/")
            or normalized.startswith("claude")
        )

    @staticmethod
    def _exception_status_code(exc: Exception) -> int | None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is not None:
            return int(status)
        status = getattr(exc, "status_code", None)
        return int(status) if status is not None else None

    def _call_litellm(
        self,
        prompt: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
    ) -> str:
        litellm = import_module("litellm")
        try:
            litellm.suppress_debug_info = True
        except Exception:
            pass
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 8192,
            "timeout": min(20.0, timeout_seconds or 20.0),
        }
        if api_key:
            kwargs["api_key"] = api_key
        if tools:
            kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice
        response = litellm.completion(**kwargs)
        if isinstance(response, dict):
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_arguments = self._tool_call_arguments(message)
            if tool_arguments:
                return tool_arguments
            return str(message.get("content") or "").strip()
        choice = response.choices[0]
        tool_arguments = self._tool_call_arguments(choice.message)
        if tool_arguments:
            return tool_arguments
        return str(choice.message.content or "").strip()

    def _call_litellm_vision(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        model: str,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        litellm = import_module("litellm")
        try:
            litellm.suppress_debug_info = True
        except Exception:
            pass
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": self._image_data_url(image)},
            }
            for image in images
        )
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "top_p": 0.8,
            "max_tokens": 8192,
            "timeout": min(45.0, timeout_seconds or 45.0),
        }
        if api_key:
            kwargs["api_key"] = api_key
        response = litellm.completion(**kwargs)
        if isinstance(response, dict):
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            return str(message.get("content") or "").strip()
        return str(response.choices[0].message.content or "").strip()

    @staticmethod
    def _tool_call_arguments(message: object) -> str:
        tool_calls = (
            message.get("tool_calls")
            if isinstance(message, dict)
            else getattr(message, "tool_calls", None)
        ) or []
        if not tool_calls:
            return ""
        first_call = tool_calls[0]
        function = (
            first_call.get("function")
            if isinstance(first_call, dict)
            else getattr(first_call, "function", None)
        )
        arguments = (
            function.get("arguments")
            if isinstance(function, dict)
            else getattr(function, "arguments", None)
        )
        return str(arguments or "").strip()

    def _call_google_genai(
        self,
        prompt: str,
        api_key: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        genai = import_module("google.genai")
        genai_types = import_module("google.genai.types")
        client = genai.Client(api_key=api_key)
        config = genai_types.GenerateContentConfig(
            temperature=0.2,
            top_p=0.8,
            max_output_tokens=8192,
        )
        response = client.models.generate_content(
            model=self._gemini_api_model_name(model or self.settings.primary_llm_model),
            contents=prompt,
            config=config,
        )
        return self._google_genai_response_text(response)

    @staticmethod
    def _google_genai_response_text(response: object) -> str:
        text = getattr(response, "text", None)
        if text:
            return str(text).strip()
        if isinstance(response, dict):
            text = response.get("text")
            if text:
                return str(text).strip()
            candidates = response.get("candidates") or []
        else:
            candidates = getattr(response, "candidates", None) or []
        parts: list[str] = []
        for candidate in candidates:
            content = (
                candidate.get("content")
                if isinstance(candidate, dict)
                else getattr(candidate, "content", None)
            )
            candidate_parts = (
                content.get("parts") if isinstance(content, dict) else getattr(content, "parts", [])
            )
            for part in candidate_parts or []:
                part_text = (
                    part.get("text") if isinstance(part, dict) else getattr(part, "text", "")
                )
                if part_text:
                    parts.append(str(part_text))
        return "\n".join(parts).strip()

    def _call_gemini(
        self,
        prompt: str,
        api_key: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        model_name = self._gemini_api_model_name(model or self.settings.primary_llm_model)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8,
                "maxOutputTokens": 8192,
            },
        }
        with httpx.Client(timeout=min(45.0, timeout_seconds or 45.0)) as client:
            response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
            response.raise_for_status()
        data = response.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts).strip()

    def _call_gemini_vision(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        api_key: str,
        model: str,
        timeout_seconds: float | None = None,
    ) -> str:
        model_name = self._gemini_api_model_name(model)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        )
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts.extend(
            {
                "inlineData": {
                    "mimeType": image["mime_type"],
                    "data": image["base64"],
                }
            }
            for image in images
        )
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.8,
                "maxOutputTokens": 8192,
            },
        }
        with httpx.Client(timeout=min(45.0, timeout_seconds or 45.0)) as client:
            response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
            response.raise_for_status()
        data = response.json()
        candidate_parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in candidate_parts).strip()

    @staticmethod
    def _normalize_vision_images(images: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for image in images or []:
            mime_type = str(image.get("mime_type") or image.get("mimeType") or "image/png")
            data = image.get("data")
            if isinstance(data, bytes):
                encoded = base64.b64encode(data).decode("ascii")
            else:
                encoded = str(image.get("base64") or data or "").strip()
            if not encoded:
                continue
            normalized.append({"mime_type": mime_type, "base64": encoded})
        return normalized

    @staticmethod
    def _image_data_url(image: dict[str, str]) -> str:
        return f"data:{image['mime_type']};base64,{image['base64']}"
