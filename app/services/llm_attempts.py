from __future__ import annotations

from collections import Counter


LLM_ATTEMPT_OUTCOME_CATEGORIES = {
    "dependency_unavailable": "dependency_unavailable",
    "empty_response": "empty_response",
    "missing_api_key": "configuration_error",  # pragma: allowlist secret
    "missing_model": "configuration_error",
    "provider_error": "provider_error",
    "quota_cooldown": "rate_limited",
    "quota_daily_exhausted": "rate_limited",
    "sdk_error": "provider_error",
    "timeout": "timeout",
    "transport_error": "network_error",
}


def summarize_llm_attempts(
    attempts: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> dict:
    rows = [attempt for attempt in attempts or [] if isinstance(attempt, dict)]
    outcome_counts = Counter(str(attempt.get("outcome") or "unknown") for attempt in rows)
    failed_attempts = [
        attempt for attempt in rows if str(attempt.get("outcome") or "") != "success"
    ]
    failure_categories = [llm_attempt_failure_category(attempt) for attempt in failed_attempts]
    http_status_counts = Counter(
        str(attempt.get("status")) for attempt in rows if attempt.get("status") is not None
    )
    last_failure = next(
        (attempt for attempt in reversed(rows) if str(attempt.get("outcome") or "") != "success"),
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
        "primary_failure_category": (
            category_counts.most_common(1)[0][0] if category_counts else None
        ),
        "last_failure_category": (
            llm_attempt_failure_category(last_failure) if last_failure else None
        ),
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
            str(attempt.get(key)) for attempt in attempts if attempt.get(key) not in {None, ""}
        )
    )
