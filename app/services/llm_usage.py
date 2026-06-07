from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from app.db.session import session_scope
from app.services.persistence import LLMUsageRepository


LOGGER = logging.getLogger(__name__)


def record_llm_usage_from_report_execution(
    report_execution: dict | None,
    *,
    operation: str = "report_generation",
    report_id: int | None = None,
    run_id: int | None = None,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
    logger: logging.Logger | None = None,
) -> dict | None:
    """Persist local LLM usage telemetry without making report generation fragile."""
    try:
        with session_scope_factory() as session:
            record = llm_usage_repository_cls(session).create_from_report_execution(
                operation=operation,
                report_execution=report_execution,
                report_id=report_id,
                run_id=run_id,
            )
        return llm_usage_repository_cls.to_dict(record) if record is not None else None
    except Exception as exc:
        (logger or LOGGER).debug("failed to persist LLM usage telemetry: %s", exc, exc_info=True)
        return None


def list_llm_usage_records(
    *,
    limit: int = 50,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
) -> list[dict[str, Any]]:
    with session_scope_factory() as session:
        records = llm_usage_repository_cls(session).latest(max(1, min(int(limit), 500)))
    return [llm_usage_repository_cls.to_dict(record) for record in records]


def summarize_llm_usage_records(
    *,
    days: int = 7,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
    clock: Callable[[], datetime] = datetime.utcnow,
) -> dict[str, Any]:
    safe_days = max(1, min(int(days or 7), 90))
    end = clock()
    since = end - timedelta(days=safe_days)
    with session_scope_factory() as session:
        repository = llm_usage_repository_cls(session)
        records = [repository.to_dict(record) for record in repository.since(since)]
    rows = [_normalized_usage_row(record) for record in records]
    return {
        "window": {
            "days": safe_days,
            "start": since.isoformat(),
            "end": end.isoformat(),
        },
        "totals": _usage_totals(rows),
        "by_model": _aggregate_usage(rows, "model"),
        "by_operation": _aggregate_usage(rows, "operation"),
        "daily": _aggregate_usage(rows, "date"),
        "recent": rows[-20:],
    }


def _normalized_usage_row(record: dict[str, Any]) -> dict[str, Any]:
    created_at = str(record.get("created_at") or "")
    date = created_at[:10] if len(created_at) >= 10 else "unknown"
    return {
        "created_at": created_at,
        "date": date,
        "operation": str(record.get("operation") or "unknown"),
        "model": str(record.get("model") or "unknown"),
        "provider": str(record.get("provider") or "unknown"),
        "fallback": bool(record.get("fallback")),
        "fallback_path_used": bool(record.get("fallback_path_used")),
        "latency_ms": _float(record.get("latency_ms")),
        "total_token_estimate": _int(record.get("total_token_estimate")),
        "estimated_cost_usd": _float(record.get("estimated_cost_usd")),
        "attempt_count": _int(record.get("attempt_count")),
        "retryable_failure_count": _int(record.get("retryable_failure_count")),
        "primary_failure_category": record.get("primary_failure_category"),
    }


def _usage_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latency_values = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    return {
        "request_count": len(rows),
        "total_token_estimate": sum(row["total_token_estimate"] or 0 for row in rows),
        "estimated_cost_usd": round(sum(row["estimated_cost_usd"] or 0.0 for row in rows), 6),
        "fallback_count": sum(1 for row in rows if row["fallback"]),
        "fallback_path_count": sum(1 for row in rows if row["fallback_path_used"]),
        "retryable_failure_count": sum(row["retryable_failure_count"] or 0 for row in rows),
        "avg_latency_ms": round(sum(latency_values) / len(latency_values), 2)
        if latency_values
        else None,
    }


def _aggregate_usage(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get(key) or "unknown"), []).append(row)
    aggregated = [
        {
            key: bucket_key,
            **_usage_totals(bucket_rows),
        }
        for bucket_key, bucket_rows in buckets.items()
    ]
    if key == "date":
        return sorted(aggregated, key=lambda item: str(item[key]))
    return sorted(
        aggregated,
        key=lambda item: (
            -int(item["total_token_estimate"] or 0),
            -int(item["request_count"] or 0),
            str(item[key]),
        ),
    )


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
