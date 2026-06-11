from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from app.core.time import utc_now_naive
from app.db.session import session_scope
from app.services.latency_metrics import latency_distribution
from app.services.llm_observability import llm_cost_budget_status, llm_observability_status
from app.services.llm_usage_repository import LLMUsageRepository


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
    settings: Any | None = None,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
    clock: Callable[[], datetime] = utc_now_naive,
) -> dict[str, Any]:
    safe_days = max(1, min(int(days or 7), 90))
    end = clock()
    since = end - timedelta(days=safe_days)
    with session_scope_factory() as session:
        repository = llm_usage_repository_cls(session)
        records = [repository.to_dict(record) for record in repository.since(since)]
    rows = [_normalized_usage_row(record) for record in records]
    totals = _usage_totals(rows)
    summary = {
        "window": {
            "days": safe_days,
            "start": since.isoformat(),
            "end": end.isoformat(),
        },
        "totals": totals,
        "by_model": _aggregate_usage(rows, "model"),
        "by_operation": _aggregate_usage(rows, "operation"),
        "daily": _aggregate_usage(rows, "date"),
        "recent": rows[-20:],
    }
    if settings is not None:
        cost_budget = llm_cost_budget_status(
            settings,
            estimated_cost_usd=float(totals.get("estimated_cost_usd") or 0.0),
            days=safe_days,
        )
        observability = llm_observability_status(settings)
        summary["cost_budget"] = cost_budget
        summary["alerts"] = _usage_alerts(totals, cost_budget, observability)
    return summary


def _normalized_usage_row(record: dict[str, Any]) -> dict[str, Any]:
    created_at = str(record.get("created_at") or "")
    date = created_at[:10] if len(created_at) >= 10 else "unknown"
    observability = (
        record.get("observability") if isinstance(record.get("observability"), dict) else {}
    )
    routing_decision = (
        observability.get("routing_decision")
        if isinstance(observability.get("routing_decision"), dict)
        else {}
    )
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
        "selected_model_rank": _int(
            observability.get("selected_model_rank")
            if observability.get("selected_model_rank") is not None
            else routing_decision.get("selected_model_rank")
        ),
        "selected_routing_tier": (
            observability.get("selected_routing_tier")
            or routing_decision.get("selected_routing_tier")
        ),
        "routing_reason": (
            routing_decision.get("routing_reason") or observability.get("routing_reason")
        ),
        "quota_skip_count": _int(
            observability.get("quota_skip_count")
            if observability.get("quota_skip_count") is not None
            else routing_decision.get("quota_skip_count")
        )
        or 0,
        "daily_quota_skip_count": _int(
            observability.get("daily_quota_skip_count")
            if observability.get("daily_quota_skip_count") is not None
            else routing_decision.get("daily_quota_skip_count")
        )
        or 0,
        "cooldown_skip_count": _int(
            observability.get("cooldown_skip_count")
            if observability.get("cooldown_skip_count") is not None
            else routing_decision.get("cooldown_skip_count")
        )
        or 0,
        "degraded_from_primary": bool(
            observability.get("degraded_from_primary")
            if observability.get("degraded_from_primary") is not None
            else routing_decision.get("degraded_from_primary")
        ),
        "high_quota_fallback_used": bool(routing_decision.get("high_quota_fallback_used")),
    }


def _usage_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latency_values = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    latency_summary = latency_distribution(latency_values)
    return {
        "request_count": len(rows),
        "total_token_estimate": sum(row["total_token_estimate"] or 0 for row in rows),
        "estimated_cost_usd": round(sum(row["estimated_cost_usd"] or 0.0 for row in rows), 6),
        "fallback_count": sum(1 for row in rows if row["fallback"]),
        "fallback_path_count": sum(1 for row in rows if row["fallback_path_used"]),
        "retryable_failure_count": sum(row["retryable_failure_count"] or 0 for row in rows),
        "quota_skip_count": sum(row["quota_skip_count"] or 0 for row in rows),
        "daily_quota_skip_count": sum(row["daily_quota_skip_count"] or 0 for row in rows),
        "cooldown_skip_count": sum(row["cooldown_skip_count"] or 0 for row in rows),
        "degraded_from_primary_count": sum(1 for row in rows if row["degraded_from_primary"]),
        "high_quota_fallback_count": sum(1 for row in rows if row["high_quota_fallback_used"]),
        "avg_latency_ms": latency_summary["avg"],
        "p95_latency_ms": latency_summary["p95"],
        "max_latency_ms": latency_summary["max"],
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


def _usage_alerts(
    totals: dict[str, Any], cost_budget: dict[str, Any], observability: dict[str, Any]
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    budget_status = str(cost_budget.get("status") or "")
    if budget_status == "exceeded":
        alerts.append(
            {
                "severity": "error",
                "code": "llm_cost_budget_exceeded",
                "message": "LLM 估算成本已超過設定期間預算。",
            }
        )
    elif budget_status == "warning":
        alerts.append(
            {
                "severity": "warning",
                "code": "llm_cost_budget_warning",
                "message": "LLM 估算成本接近設定期間預算。",
            }
        )
    if totals.get("request_count") and not observability.get("cost_rate_card_configured"):
        alerts.append(
            {
                "severity": "info",
                "code": "llm_cost_rate_card_missing",
                "message": "尚未設定成本費率前，LLM 用量只會以 Token 估算追蹤。",
            }
        )
    if int(totals.get("fallback_path_count") or 0):
        alerts.append(
            {
                "severity": "warning",
                "code": "llm_fallback_used",
                "message": "部分 LLM 呼叫使用後援路由。",
            }
        )
    if int(totals.get("retryable_failure_count") or 0):
        alerts.append(
            {
                "severity": "warning",
                "code": "llm_retryable_failures",
                "message": "選定期間內觀察到可重試的 LLM 失敗。",
            }
        )
    if int(totals.get("quota_skip_count") or 0):
        alerts.append(
            {
                "severity": "info",
                "code": "llm_quota_routing_skips",
                "message": "部分呼叫在選擇後援前略過額度用完或冷卻中的模型。",
            }
        )
    return alerts


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
