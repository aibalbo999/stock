from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.llm_model_routing_policy import normalize_model_name

NON_REQUEST_ATTEMPT_OUTCOMES = {
    "dependency_unavailable",
    "missing_api_key",
    "missing_model",
    "quota_cooldown",
    "quota_daily_exhausted",
    "timeout",
}


def usage_by_model(records: list[dict]) -> dict[str, dict]:
    usage: dict[str, dict] = {}
    for record in records:
        model = str(record.get("model") or "unknown")
        model_key = normalize_model_name(model)
        request_counts = _model_request_counts(record)
        if not request_counts:
            request_counts = {model_key: 1}
        retryable_failures = _retryable_failures_by_model(record)
        for attempted_model_key, request_count in request_counts.items():
            bucket = _usage_bucket(
                usage,
                attempted_model_key,
                _display_model_for_key(attempted_model_key, record),
            )
            bucket["request_count"] += int(request_count)
            bucket["retryable_failure_count"] += int(
                retryable_failures.get(attempted_model_key, 0)
            )

        final_bucket = _usage_bucket(usage, model_key, model)
        final_bucket["completion_count"] += 1
        final_bucket["total_token_estimate"] += int(record.get("total_token_estimate") or 0)
        final_bucket["estimated_cost_usd"] += float(record.get("estimated_cost_usd") or 0.0)
        final_bucket["fallback_count"] += 1 if record.get("fallback") else 0
        if not retryable_failures:
            final_bucket["retryable_failure_count"] += int(
                record.get("retryable_failure_count") or 0
            )
    return usage


def quota_health_by_model(
    records: list[dict],
    *,
    now_utc_naive: datetime,
    default_cooldown_seconds: float,
) -> dict[str, dict]:
    health: dict[str, dict] = {}
    for record in records:
        record_created_at = _parse_record_datetime(record.get("created_at"))
        attempts = record.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            model_key = normalize_model_name(str(attempt.get("model") or ""))
            if not model_key:
                continue
            bucket = health.setdefault(
                model_key,
                {
                    "model": _display_model_for_key(model_key, record),
                    "quota_hit_count": 0,
                    "daily_quota_skip_count": 0,
                    "cooldown_skip_count": 0,
                    "quota_skip_count": 0,
                    "active_cooldown_seconds": 0,
                    "last_quota_hit_at": None,
                },
            )
            outcome = str(attempt.get("outcome") or "")
            status = _safe_int(attempt.get("status"))
            if status == 429:
                bucket["quota_hit_count"] += 1
                _record_last_quota_hit(bucket, record_created_at)
                cooldown = _attempt_cooldown_seconds(
                    attempt,
                    default_seconds=default_cooldown_seconds,
                )
                bucket["active_cooldown_seconds"] = max(
                    int(bucket.get("active_cooldown_seconds") or 0),
                    _cooldown_remaining_seconds(
                        record_created_at,
                        now_utc_naive=now_utc_naive,
                        cooldown_seconds=cooldown,
                    ),
                )
            if outcome == "quota_daily_exhausted":
                bucket["daily_quota_skip_count"] += 1
                bucket["quota_skip_count"] += 1
            elif outcome == "quota_cooldown":
                bucket["cooldown_skip_count"] += 1
                bucket["quota_skip_count"] += 1
                cooldown = _attempt_cooldown_seconds(
                    attempt,
                    default_seconds=default_cooldown_seconds,
                )
                bucket["active_cooldown_seconds"] = max(
                    int(bucket.get("active_cooldown_seconds") or 0),
                    _cooldown_remaining_seconds(
                        record_created_at,
                        now_utc_naive=now_utc_naive,
                        cooldown_seconds=cooldown,
                    ),
                )
    return health


def _usage_bucket(usage: dict[str, dict], model_key: str, display_model: str) -> dict:
    return usage.setdefault(
        model_key,
        {
            "model": display_model or model_key,
            "completion_count": 0,
            "request_count": 0,
            "total_token_estimate": 0,
            "estimated_cost_usd": 0.0,
            "fallback_count": 0,
            "retryable_failure_count": 0,
        },
    )


def _model_request_counts(record: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    attempts = record.get("attempts")
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            outcome = str(attempt.get("outcome") or "")
            if outcome in NON_REQUEST_ATTEMPT_OUTCOMES:
                continue
            model_key = normalize_model_name(str(attempt.get("model") or ""))
            if model_key:
                counts[model_key] = counts.get(model_key, 0) + 1
    if counts:
        return counts

    models_tried = record.get("models_tried")
    if isinstance(models_tried, list):
        for model in models_tried:
            model_key = normalize_model_name(str(model or ""))
            if model_key and model_key not in counts:
                counts[model_key] = 1
    return counts


def _retryable_failures_by_model(record: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    attempts = record.get("attempts")
    if not isinstance(attempts, list):
        return counts
    for attempt in attempts:
        if not isinstance(attempt, dict) or attempt.get("retryable") is not True:
            continue
        outcome = str(attempt.get("outcome") or "")
        if outcome in {"quota_cooldown", "quota_daily_exhausted"}:
            continue
        model_key = normalize_model_name(str(attempt.get("model") or ""))
        if model_key:
            counts[model_key] = counts.get(model_key, 0) + 1
    return counts


def _display_model_for_key(model_key: str, record: dict) -> str:
    for value in _record_model_values(record):
        if normalize_model_name(value) == model_key:
            return value
    return model_key


def _record_model_values(record: dict) -> list[str]:
    values: list[str] = []
    model = str(record.get("model") or "").strip()
    if model:
        values.append(model)
    models_tried = record.get("models_tried")
    if isinstance(models_tried, list):
        values.extend(str(item or "").strip() for item in models_tried if str(item or "").strip())
    attempts = record.get("attempts")
    if isinstance(attempts, list):
        values.extend(
            str(attempt.get("model") or "").strip()
            for attempt in attempts
            if isinstance(attempt, dict) and str(attempt.get("model") or "").strip()
        )
    return list(dict.fromkeys(values))


def _safe_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_record_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _record_last_quota_hit(bucket: dict, created_at: datetime | None) -> None:
    if created_at is None:
        return
    previous = _parse_record_datetime(bucket.get("last_quota_hit_at"))
    if previous is None or created_at >= previous:
        bucket["last_quota_hit_at"] = created_at.isoformat()


def _attempt_cooldown_seconds(attempt: dict, *, default_seconds: float) -> float:
    value = attempt.get("cooldown_seconds")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, parsed if parsed > 0 else float(default_seconds or 0.0))


def _cooldown_remaining_seconds(
    created_at: datetime | None,
    *,
    now_utc_naive: datetime,
    cooldown_seconds: float,
) -> int:
    if created_at is None or cooldown_seconds <= 0:
        return 0
    until = created_at + timedelta(seconds=float(cooldown_seconds))
    return max(0, int((until - now_utc_naive).total_seconds()))


__all__ = ["NON_REQUEST_ATTEMPT_OUTCOMES", "quota_health_by_model", "usage_by_model"]
