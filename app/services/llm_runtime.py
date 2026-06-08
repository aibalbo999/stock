from __future__ import annotations

from dataclasses import dataclass, field

import httpx


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


__all__ = [
    "DEFAULT_BASE_RETRY_DELAY_SECONDS",
    "DEFAULT_MAX_RETRIES_PER_KEY",
    "DEFAULT_MAX_RETRY_DELAY_SECONDS",
    "DEFAULT_MODEL_QUOTA_COOLDOWN_SECONDS",
    "DEFAULT_TOTAL_TIMEOUT_SECONDS",
    "LLMResult",
    "RETRYABLE_HTTP_STATUSES",
    "ROTATABLE_HTTP_STATUSES",
    "exception_status_code",
    "llm_attempt_record",
    "llm_retry_delay_seconds",
]
