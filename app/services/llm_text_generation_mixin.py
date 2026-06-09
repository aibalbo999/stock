from __future__ import annotations

from time import monotonic
from typing import Any

import httpx

from app.services.llm_models import (
    gemini_model_candidates,
    litellm_key_candidates,
    litellm_model_candidates,
    litellm_model_requires_api_key,
)
from app.services.llm_runtime import (
    LLMResult,
    llm_error_retryable as _llm_error_retryable,
    llm_failure_result as _llm_failure_result,
    llm_should_retry_after_error as _llm_should_retry_after_error,
    llm_should_stop_after_status as _llm_should_stop_after_status,
    llm_success_result as _llm_success_result,
)


class LLMTextGenerationMixin:
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
                            return _llm_success_result(
                                text=text,
                                key_index=key_index,
                                model=model_name,
                                provider="gemini_http",
                                attempts=attempts,
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
                                retryable=_llm_error_retryable(status),
                            )
                        )
                        if _llm_should_stop_after_status(
                            status,
                            use_model_fallback=use_model_fallback,
                        ):
                            should_stop = True
                            break
                        if _llm_should_retry_after_error(
                            status,
                            attempt=attempt,
                            max_retries=max_retries,
                            deadline=deadline,
                            use_model_fallback=use_model_fallback,
                            require_retryable_status=True,
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
                        if _llm_should_retry_after_error(
                            None,
                            attempt=attempt,
                            max_retries=max_retries,
                            deadline=deadline,
                            use_model_fallback=False,
                            require_retryable_status=False,
                        ):
                            self._sleep_before_retry(None, attempt)
                            continue
                        break
                if should_stop:
                    break

        return _llm_failure_result(
            text=(
                "LLM 呼叫失敗，已改用規則引擎產生報告草稿。"
                f"輪調嘗試：{'; '.join(errors) if errors else '無'}"
            ),
            prior_attempts=attempts,
        )

    def _generate_with_google_genai(self, prompt: str) -> LLMResult:
        try:
            self._import_module("google.genai")
        except Exception as exc:
            return _llm_failure_result(
                text=f"Google GenAI SDK unavailable: {exc.__class__.__name__}",
                provider="google_genai",
                attempt_record_func=self._attempt_record,
                attempt_provider="google_genai",
                attempt_model=self.settings.primary_llm_model,
                outcome="dependency_unavailable",
                error=exc.__class__.__name__,
            )

        if len(self.rotator) == 0:
            return _llm_failure_result(
                text="Google GenAI SDK has no configured API key",
                provider="google_genai",
                attempt_record_func=self._attempt_record,
                attempt_provider="google_genai",
                attempt_model=self.settings.primary_llm_model,
                outcome="missing_api_key",
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
                            return _llm_success_result(
                                text=text,
                                key_index=key_index,
                                model=model_name,
                                provider="google_genai",
                                attempts=attempts,
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
                                retryable=_llm_error_retryable(status),
                            )
                        )
                        if _llm_should_stop_after_status(
                            status,
                            use_model_fallback=use_model_fallback,
                        ):
                            should_stop = True
                            break
                        if _llm_should_retry_after_error(
                            status,
                            attempt=attempt,
                            max_retries=max_retries,
                            deadline=deadline,
                            use_model_fallback=use_model_fallback,
                            require_retryable_status=False,
                        ):
                            self._sleep_before_retry(getattr(exc, "response", None), attempt)
                            continue
                        break
                if should_stop:
                    break

        return _llm_failure_result(
            text="Google GenAI SDK 呼叫失敗，將改走既有 Gemini HTTP 或規則引擎。"
            + ("；".join(errors) if errors else ""),
            provider="google_genai",
            prior_attempts=attempts,
        )

    def _generate_with_litellm(
        self,
        prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
    ) -> LLMResult:
        try:
            self._import_module("litellm")
        except Exception as exc:
            return _llm_failure_result(
                text=f"LiteLLM unavailable: {exc.__class__.__name__}",
                provider="litellm",
                attempt_record_func=self._attempt_record,
                attempt_provider="litellm",
                attempt_model=None,
                outcome="dependency_unavailable",
                error=exc.__class__.__name__,
            )

        models = litellm_model_candidates(self.settings)
        if not models:
            return _llm_failure_result(
                text="LiteLLM has no configured model candidates",
                provider="litellm",
                attempt_record_func=self._attempt_record,
                attempt_provider="litellm",
                attempt_model=None,
                outcome="missing_model",
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
                            return _llm_success_result(
                                text=text,
                                key_index=key_index,
                                model=model,
                                provider="litellm",
                                attempts=attempts,
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
                                retryable=_llm_error_retryable(status),
                            )
                        )
                        if _llm_should_stop_after_status(
                            status,
                            use_model_fallback=False,
                        ):
                            break
                        if status == 429 and use_fast_model_chain_fallback:
                            stop_model_after_quota = True
                            break
                        if _llm_should_retry_after_error(
                            status,
                            attempt=attempt,
                            max_retries=max_retries,
                            deadline=deadline,
                            use_model_fallback=use_fast_model_chain_fallback,
                            require_retryable_status=False,
                        ):
                            self._sleep_before_retry(getattr(exc, "response", None), attempt)
                            continue
                        break

        return _llm_failure_result(
            text="LiteLLM 呼叫失敗，將改走既有 Gemini HTTP 或規則引擎。"
            + ("；".join(errors) if errors else ""),
            provider="litellm",
            prior_attempts=attempts,
        )


__all__ = ["LLMTextGenerationMixin"]
