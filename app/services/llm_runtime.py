from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic

import httpx

from app.services.llm_models import model_quota_cooldown_key
from app.services.llm_quota import LLMQuotaGovernanceService, normalize_model_name


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
_UNSET = object()

AttemptRecordFunc = Callable[..., dict[str, object]]


def llm_attempt_record(
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


def llm_success_result(
    *,
    text: str,
    provider: str,
    model: str | None,
    key_index: int | None = None,
    attempts: Sequence[dict[str, object]] = (),
) -> LLMResult:
    return LLMResult(
        text=text,
        key_index=key_index,
        model=model,
        provider=provider,
        attempts=tuple(attempts),
    )


def llm_failure_result(
    *,
    text: str,
    provider: str | None = None,
    model: str | None = None,
    prior_attempts: Sequence[dict[str, object]] = (),
    attempt_record_func: AttemptRecordFunc | None = None,
    attempt_provider: str | None = None,
    attempt_model: str | None | object = _UNSET,
    outcome: str | None = None,
    key_index: int | None = None,
    attempt: int | None = None,
    status: int | None = None,
    error: str | None = None,
    retryable: bool | None = None,
    cooldown_seconds: float | None = None,
) -> LLMResult:
    attempts = list(prior_attempts)
    if attempt_record_func is not None and outcome:
        record_model = model if attempt_model is _UNSET else attempt_model
        attempts.append(
            attempt_record_func(
                provider=attempt_provider or provider or "unknown",
                model=record_model,
                outcome=outcome,
                key_index=key_index,
                attempt=attempt,
                status=status,
                error=error,
                retryable=retryable,
                cooldown_seconds=cooldown_seconds,
            )
        )
    return LLMResult(
        text=text,
        provider=provider,
        model=model,
        fallback=True,
        attempts=tuple(attempts),
    )


def llm_retry_delay_seconds(
    response: httpx.Response | None,
    attempt: int,
    *,
    base_retry_delay_seconds: float,
    max_retry_delay_seconds: float,
) -> float:
    max_delay = max(0.0, float(max_retry_delay_seconds))
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max_delay, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return min(max_delay, max(0.0, float(base_retry_delay_seconds)) * (2**attempt))


def exception_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        return int(status)
    status = getattr(exc, "status_code", None)
    return int(status) if status is not None else None


def llm_error_retryable(status: int | None) -> bool:
    return True if status is None else int(status) in RETRYABLE_HTTP_STATUSES


def llm_should_stop_after_status(
    status: int | None,
    *,
    use_model_fallback: bool,
) -> bool:
    if status is not None and int(status) not in ROTATABLE_HTTP_STATUSES:
        return True
    return status == 429 and use_model_fallback


def llm_should_retry_after_error(
    status: int | None,
    *,
    attempt: int,
    max_retries: int,
    deadline: float,
    use_model_fallback: bool,
    require_retryable_status: bool,
    now: float | None = None,
) -> bool:
    if llm_should_stop_after_status(status, use_model_fallback=use_model_fallback):
        return False
    if attempt >= max(0, int(max_retries)):
        return False
    if require_retryable_status and not llm_error_retryable(status):
        return False
    now_value = monotonic() if now is None else float(now)
    return now_value < deadline


def model_quota_cooldown_remaining(model: str, *, now: float | None = None) -> float:
    key = model_quota_cooldown_key(model)
    now_value = monotonic() if now is None else float(now)
    with _model_quota_cooldowns_lock:
        until = _model_quota_cooldowns.get(key, 0.0)
        if until <= now_value:
            _model_quota_cooldowns.pop(key, None)
            return 0.0
        return until - now_value


def start_model_quota_cooldown(
    model: str,
    cooldown_seconds: float,
    *,
    now: float | None = None,
) -> None:
    if cooldown_seconds <= 0:
        return
    key = model_quota_cooldown_key(model)
    now_value = monotonic() if now is None else float(now)
    until = now_value + cooldown_seconds
    with _model_quota_cooldowns_lock:
        _model_quota_cooldowns[key] = max(_model_quota_cooldowns.get(key, 0.0), until)


def daily_quota_exhausted_model_keys(settings: object) -> set[str]:
    if not bool(getattr(settings, "llm_quota_hard_routing_enabled", True)):
        return set()
    try:
        return LLMQuotaGovernanceService(settings_provider=lambda: settings).exhausted_model_keys()
    except Exception:
        return set()


def model_daily_quota_exhausted(model: str, exhausted_model_keys: set[str]) -> bool:
    return normalize_model_name(model) in exhausted_model_keys


__all__ = [
    "DEFAULT_BASE_RETRY_DELAY_SECONDS",
    "DEFAULT_MAX_RETRIES_PER_KEY",
    "DEFAULT_MAX_RETRY_DELAY_SECONDS",
    "DEFAULT_MODEL_QUOTA_COOLDOWN_SECONDS",
    "DEFAULT_TOTAL_TIMEOUT_SECONDS",
    "LLMResult",
    "RETRYABLE_HTTP_STATUSES",
    "ROTATABLE_HTTP_STATUSES",
    "_model_quota_cooldowns",
    "_model_quota_cooldowns_lock",
    "daily_quota_exhausted_model_keys",
    "exception_status_code",
    "llm_attempt_record",
    "llm_error_retryable",
    "llm_failure_result",
    "llm_retry_delay_seconds",
    "llm_should_retry_after_error",
    "llm_should_stop_after_status",
    "llm_success_result",
    "model_daily_quota_exhausted",
    "model_quota_cooldown_remaining",
    "start_model_quota_cooldown",
]
