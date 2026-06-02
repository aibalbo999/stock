from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from importlib import import_module
from threading import Lock
from time import monotonic, sleep
from typing import Optional

import httpx

from app.core.config import get_settings

RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
ROTATABLE_HTTP_STATUSES = {401, 403, *RETRYABLE_HTTP_STATUSES}
DEFAULT_MAX_RETRIES_PER_KEY = 2
DEFAULT_BASE_RETRY_DELAY_SECONDS = 0.5
DEFAULT_MAX_RETRY_DELAY_SECONDS = 5.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 60.0
LLM_ATTEMPT_OUTCOME_CATEGORIES = {
    "dependency_unavailable": "dependency_unavailable",
    "empty_response": "empty_response",
    "missing_api_key": "configuration_error",
    "missing_model": "configuration_error",
    "provider_error": "provider_error",
    "sdk_error": "provider_error",
    "timeout": "timeout",
    "transport_error": "network_error",
}


@dataclass(frozen=True)
class LLMResult:
    text: str
    key_index: int | None = None
    model: str | None = None
    provider: str | None = None
    fallback: bool = False
    attempts: tuple[dict[str, object], ...] = field(default_factory=tuple)


class APIKeyRotator:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self._index = 0
        self._lock = Lock()

    def __len__(self) -> int:
        return len(self.keys)

    def candidates(self) -> list[tuple[int, str]]:
        if not self.keys:
            return []
        with self._lock:
            start = self._index
            self._index = (self._index + 1) % len(self.keys)
        return [
            ((start + offset) % len(self.keys), self.keys[(start + offset) % len(self.keys)])
            for offset in range(len(self.keys))
        ]


_rotator_cache: dict[tuple[str, ...], APIKeyRotator] = {}
_rotator_cache_lock = Lock()


def get_shared_rotator(keys: list[str]) -> APIKeyRotator:
    fingerprint = tuple(keys)
    with _rotator_cache_lock:
        if fingerprint not in _rotator_cache:
            _rotator_cache[fingerprint] = APIKeyRotator(keys)
        return _rotator_cache[fingerprint]


def summarize_llm_attempts(attempts: tuple[dict[str, object], ...] | list[dict[str, object]]) -> dict:
    rows = [attempt for attempt in attempts or [] if isinstance(attempt, dict)]
    outcome_counts = Counter(str(attempt.get("outcome") or "unknown") for attempt in rows)
    failed_attempts = [
        attempt
        for attempt in rows
        if str(attempt.get("outcome") or "") != "success"
    ]
    failure_categories = [
        llm_attempt_failure_category(attempt)
        for attempt in failed_attempts
    ]
    http_status_counts = Counter(
        str(attempt.get("status"))
        for attempt in rows
        if attempt.get("status") is not None
    )
    last_failure = next(
        (
            attempt
            for attempt in reversed(rows)
            if str(attempt.get("outcome") or "") != "success"
        ),
        {},
    )
    final_attempt = rows[-1] if rows else {}
    first_attempt = rows[0] if rows else {}
    providers_tried = _ordered_attempt_values(rows, "provider")
    models_tried = _ordered_attempt_values(rows, "model")
    final_outcome = final_attempt.get("outcome")
    final_success = final_outcome == "success"
    retry_used = any(_safe_int(attempt.get("attempt")) > 1 for attempt in rows)
    provider_fallback_used = bool(
        final_success
        and providers_tried
        and final_attempt.get("provider") is not None
        and str(first_attempt.get("provider") or "") != str(final_attempt.get("provider") or "")
    )
    model_fallback_used = bool(
        final_success
        and models_tried
        and final_attempt.get("model") is not None
        and str(first_attempt.get("model") or "") != str(final_attempt.get("model") or "")
    )
    category_counts = Counter(failure_categories)
    return {
        "attempt_count": len(rows),
        "providers_tried": providers_tried,
        "models_tried": models_tried,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "failure_category_counts": dict(sorted(category_counts.items())),
        "http_status_counts": dict(sorted(http_status_counts.items())),
        "failed_attempt_count": len(failed_attempts),
        "successful_attempt_count": int(outcome_counts.get("success", 0)),
        "retryable_failure_count": sum(1 for attempt in rows if attempt.get("retryable") is True),
        "retry_used": retry_used,
        "success_after_failure": bool(final_success and failed_attempts),
        "provider_fallback_used": provider_fallback_used,
        "model_fallback_used": model_fallback_used,
        "fallback_path_used": bool(provider_fallback_used or model_fallback_used),
        "primary_failure_category": category_counts.most_common(1)[0][0] if category_counts else None,
        "last_failure_category": llm_attempt_failure_category(last_failure) if last_failure else None,
        "primary_provider": first_attempt.get("provider"),
        "primary_model": first_attempt.get("model"),
        "final_provider": final_attempt.get("provider"),
        "final_model": final_attempt.get("model"),
        "final_outcome": final_outcome,
        "final_success": final_success,
    }


def llm_attempt_failure_category(attempt: dict[str, object]) -> str:
    outcome = str(attempt.get("outcome") or "unknown")
    if outcome == "success":
        return "success"
    status = attempt.get("status")
    if status is not None:
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            return "http_error"
        if status_code in {401, 403}:
            return "auth_or_permission_error"
        if status_code == 429:
            return "rate_limited"
        if status_code in {500, 502, 503, 504}:
            return "upstream_error"
        return "http_error"
    return LLM_ATTEMPT_OUTCOME_CATEGORIES.get(outcome, "unknown_error")


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _ordered_attempt_values(attempts: list[dict[str, object]], key: str) -> list[str]:
    return list(
        dict.fromkeys(
            str(attempt.get(key))
            for attempt in attempts
            if attempt.get(key) not in {None, ""}
        )
    )


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
        key_note = f"Gemini API key pool index：{result.key_index}" if result.key_index is not None else "Gemini API"
        provider_note = f"，provider={result.provider}" if result.provider else ""
        return f"{result.text}\n\n模型狀態：{key_note}，model={result.model}{provider_note}"

    def generate_with_metadata(self, prompt: str) -> LLMResult:
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

    def _generate_with_gemini_http(
        self,
        prompt: str,
        prior_attempts: tuple[dict[str, object], ...] = (),
    ) -> LLMResult:
        errors: list[str] = []
        attempts: list[dict[str, object]] = list(prior_attempts)
        deadline = monotonic() + self.total_timeout_seconds
        for key_index, api_key in self.rotator.candidates():
            if monotonic() >= deadline:
                errors.append("LLM total timeout reached before trying next key")
                attempts.append(
                    self._attempt_record(
                        provider="gemini_http",
                        model=self.settings.primary_llm_model,
                        key_index=key_index,
                        outcome="timeout",
                    )
                )
                break
            should_stop = False
            max_retries = self.max_retries_per_key
            for attempt in range(max_retries + 1):
                if monotonic() >= deadline:
                    errors.append(f"key[{key_index}] total timeout before attempt {attempt + 1}")
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=self.settings.primary_llm_model,
                            key_index=key_index,
                            attempt=attempt + 1,
                            outcome="timeout",
                        )
                    )
                    should_stop = True
                    break
                try:
                    text = self._call_gemini(prompt, api_key, timeout_seconds=max(1.0, deadline - monotonic()))
                    if text:
                        attempts.append(
                            self._attempt_record(
                                provider="gemini_http",
                                model=self.settings.primary_llm_model,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="success",
                            )
                        )
                        return LLMResult(
                            text=text,
                            key_index=key_index,
                            model=self.settings.primary_llm_model,
                            provider="gemini_http",
                            attempts=tuple(attempts),
                        )
                    errors.append(f"key[{key_index}] empty response")
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=self.settings.primary_llm_model,
                            key_index=key_index,
                            attempt=attempt + 1,
                            outcome="empty_response",
                        )
                    )
                    break
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    errors.append(f"key[{key_index}] HTTP {status} attempt {attempt + 1}")
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=self.settings.primary_llm_model,
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
                    if status in RETRYABLE_HTTP_STATUSES and attempt < max_retries and monotonic() < deadline:
                        self._sleep_before_retry(exc.response, attempt)
                        continue
                    break
                except httpx.HTTPError as exc:
                    errors.append(f"key[{key_index}] {exc.__class__.__name__} attempt {attempt + 1}")
                    attempts.append(
                        self._attempt_record(
                            provider="gemini_http",
                            model=self.settings.primary_llm_model,
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
        for key_index, api_key in self.rotator.candidates():
            max_retries = self.max_retries_per_key
            for attempt in range(max_retries + 1):
                if monotonic() >= deadline:
                    errors.append(f"key[{key_index}] total timeout before SDK attempt {attempt + 1}")
                    attempts.append(
                        self._attempt_record(
                            provider="google_genai",
                            model=self.settings.primary_llm_model,
                            key_index=key_index,
                            attempt=attempt + 1,
                            outcome="timeout",
                        )
                    )
                    break
                try:
                    text = self._call_google_genai(
                        prompt,
                        api_key,
                        timeout_seconds=max(1.0, deadline - monotonic()),
                    )
                    if text:
                        attempts.append(
                            self._attempt_record(
                                provider="google_genai",
                                model=self.settings.primary_llm_model,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="success",
                            )
                        )
                        return LLMResult(
                            text=text,
                            key_index=key_index,
                            model=self.settings.primary_llm_model,
                            provider="google_genai",
                            attempts=tuple(attempts),
                        )
                    errors.append(f"key[{key_index}] empty SDK response")
                    attempts.append(
                        self._attempt_record(
                            provider="google_genai",
                            model=self.settings.primary_llm_model,
                            key_index=key_index,
                            attempt=attempt + 1,
                            outcome="empty_response",
                        )
                    )
                    break
                except Exception as exc:
                    status = self._exception_status_code(exc)
                    status_label = f"HTTP {status}" if status is not None else exc.__class__.__name__
                    errors.append(f"key[{key_index}] SDK {status_label} attempt {attempt + 1}")
                    attempts.append(
                        self._attempt_record(
                            provider="google_genai",
                            model=self.settings.primary_llm_model,
                            key_index=key_index,
                            attempt=attempt + 1,
                            outcome="http_error" if status is not None else "sdk_error",
                            status=status,
                            error=None if status is not None else exc.__class__.__name__,
                            retryable=(status in RETRYABLE_HTTP_STATUSES) if status is not None else True,
                        )
                    )
                    if status is not None and status not in ROTATABLE_HTTP_STATUSES:
                        break
                    if attempt < max_retries and monotonic() < deadline:
                        self._sleep_before_retry(getattr(exc, "response", None), attempt)
                        continue
                    break

        return LLMResult(
            text="Google GenAI SDK 呼叫失敗，將改走既有 Gemini HTTP 或規則引擎。"
            + ("；".join(errors) if errors else ""),
            provider="google_genai",
            fallback=True,
            attempts=tuple(attempts),
        )

    def _generate_with_litellm(self, prompt: str) -> LLMResult:
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
        for model in models:
            key_candidates = self._litellm_key_candidates(model)
            if use_fast_model_chain_fallback and len(key_candidates) > 2:
                key_candidates = key_candidates[:2]
            for key_index, api_key in key_candidates:
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
                        status_label = f"HTTP {status}" if status is not None else exc.__class__.__name__
                        errors.append(f"{model} key[{key_index}] {status_label} attempt {attempt + 1}")
                        attempts.append(
                            self._attempt_record(
                                provider="litellm",
                                model=model,
                                key_index=key_index,
                                attempt=attempt + 1,
                                outcome="http_error" if status is not None else "provider_error",
                                status=status,
                                error=None if status is not None else exc.__class__.__name__,
                                retryable=(status in RETRYABLE_HTTP_STATUSES) if status is not None else True,
                            )
                        )
                        if status is not None and status not in ROTATABLE_HTTP_STATUSES:
                            break
                        if attempt < max_retries and monotonic() < deadline:
                            self._sleep_before_retry(getattr(exc, "response", None), attempt)
                            continue
                        break

        return LLMResult(
            text="LiteLLM 呼叫失敗，將改走既有 Gemini HTTP 或規則引擎。" + ("；".join(errors) if errors else ""),
            provider="litellm",
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
        return str(
            getattr(self.settings, "llm_provider", "gemini_http") or "gemini_http"
        ).lower().replace("-", "_")

    @property
    def max_retries_per_key(self) -> int:
        return max(0, int(getattr(self.settings, "llm_max_retries_per_key", DEFAULT_MAX_RETRIES_PER_KEY)))

    @property
    def base_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "llm_base_retry_delay_seconds", DEFAULT_BASE_RETRY_DELAY_SECONDS)))

    @property
    def max_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "llm_max_retry_delay_seconds", DEFAULT_MAX_RETRY_DELAY_SECONDS)))

    @property
    def total_timeout_seconds(self) -> float:
        return max(1.0, float(getattr(self.settings, "llm_total_timeout_seconds", DEFAULT_TOTAL_TIMEOUT_SECONDS)))

    def healthcheck(self) -> LLMResult:
        return self.generate_with_metadata(
            "請只回答 ok，不要輸出任何其他文字。"
        )

    def _litellm_model_candidates(self) -> list[str]:
        models = [self._litellm_model_name(self.settings.primary_llm_model)]
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
        if (normalized.startswith("gemini/") or normalized.startswith("gemma")) and len(self.rotator) > 0:
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
        response = litellm.completion(**kwargs)
        if isinstance(response, dict):
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            return str(message.get("content") or "").strip()
        choice = response.choices[0]
        return str(choice.message.content or "").strip()

    def _call_google_genai(
        self,
        prompt: str,
        api_key: str,
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
            model=self.settings.primary_llm_model,
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
                content.get("parts")
                if isinstance(content, dict)
                else getattr(content, "parts", [])
            )
            for part in candidate_parts or []:
                part_text = part.get("text") if isinstance(part, dict) else getattr(part, "text", "")
                if part_text:
                    parts.append(str(part_text))
        return "\n".join(parts).strip()

    def _call_gemini(self, prompt: str, api_key: str, timeout_seconds: float | None = None) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.primary_llm_model}:generateContent"
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
