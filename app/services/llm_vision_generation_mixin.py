from __future__ import annotations

from time import monotonic

import httpx

from app.services.llm_models import (
    gemini_vision_model_candidates,
    is_vision_model_candidate,
    litellm_key_candidates,
    litellm_model_candidates,
    litellm_model_requires_api_key,
)
from app.services.llm_runtime import (
    LLMResult,
    llm_error_retryable as _llm_error_retryable,
    llm_failure_result as _llm_failure_result,
    llm_should_stop_after_status as _llm_should_stop_after_status,
    llm_success_result as _llm_success_result,
)


class LLMVisionGenerationMixin:
    def _generate_vision_with_litellm(
        self,
        prompt: str,
        *,
        images: list[dict[str, str]],
        model: str | None = None,
    ) -> LLMResult:
        try:
            self._import_module("litellm")
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


__all__ = ["LLMVisionGenerationMixin"]
