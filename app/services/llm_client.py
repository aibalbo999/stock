from __future__ import annotations

from importlib import import_module
from time import monotonic, sleep
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.services.api_key_rotation import APIKeyRotator, get_shared_rotator
from app.services.llm_attempts import llm_attempt_failure_category, summarize_llm_attempts
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
    llm_failure_result as _llm_failure_result,
    llm_retry_delay_seconds as _llm_retry_delay_seconds,
)
from app.services.llm_text_generation_mixin import LLMTextGenerationMixin
from app.services.llm_vision_generation_mixin import LLMVisionGenerationMixin

__all__ = [
    "APIKeyRotator",
    "LLMClient",
    "LLMResult",
    "get_shared_rotator",
    "llm_attempt_failure_category",
    "summarize_llm_attempts",
]


class LLMClient(
    LLMQuotaRoutingMixin,
    LLMProviderCallMixin,
    LLMTextGenerationMixin,
    LLMVisionGenerationMixin,
):
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
