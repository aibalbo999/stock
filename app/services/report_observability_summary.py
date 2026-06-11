from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.latency_metrics import latency_distribution
from app.services.report_observability_bottlenecks import (
    metric_float,
    metric_int,
    report_observability_bottleneck_rows,
    report_observability_recommendations,
)


def report_observability_summary_row(
    snapshot: dict[str, Any],
    parse_run_payload_func: Callable[[str | None], dict],
) -> dict:
    payload = parse_run_payload_func(snapshot.get("run_payload"))
    execution = report_execution_from_payload(payload)
    llm = execution.get("llm") if isinstance(execution.get("llm"), dict) else {}
    llm_observability = (
        llm.get("observability") if isinstance(llm.get("observability"), dict) else {}
    )
    attempt_summary = (
        llm.get("attempt_summary") if isinstance(llm.get("attempt_summary"), dict) else {}
    )
    routing_decision = (
        llm_observability.get("routing_decision")
        if isinstance(llm_observability.get("routing_decision"), dict)
        else {}
    )
    retrieval_trace = (
        execution.get("retrieval_trace")
        if isinstance(execution.get("retrieval_trace"), dict)
        else {}
    )
    reranker_status = (
        retrieval_trace.get("reranker_status")
        if isinstance(retrieval_trace.get("reranker_status"), dict)
        else {}
    )
    graph_reasoning = (
        execution.get("graph_reasoning")
        if isinstance(execution.get("graph_reasoning"), dict)
        else {}
    )
    return {
        "id": snapshot.get("id"),
        "title": snapshot.get("title"),
        "topic": snapshot.get("topic"),
        "generated_at": snapshot.get("generated_at"),
        "run_id": snapshot.get("run_id"),
        "run_source": snapshot.get("run_source"),
        "run_status": snapshot.get("run_status"),
        "model": llm.get("model"),
        "provider": llm.get("provider"),
        "fallback": bool(llm.get("fallback")),
        "fallback_path_used": bool(attempt_summary.get("fallback_path_used")),
        "attempt_count": metric_int(attempt_summary.get("attempt_count")),
        "retryable_failure_count": metric_int(
            attempt_summary.get("retryable_failure_count"),
            default=0,
        ),
        "primary_failure_category": attempt_summary.get("primary_failure_category"),
        "llm_latency_ms": metric_float(llm_observability.get("latency_ms")),
        "total_token_estimate": metric_int(llm_observability.get("total_token_estimate")),
        "estimated_cost_usd": metric_float(llm_observability.get("estimated_cost_usd")),
        "cost_tracking_mode": llm_observability.get("cost_tracking_mode"),
        "selected_model_rank": metric_int(
            llm_observability.get("selected_model_rank")
            if llm_observability.get("selected_model_rank") is not None
            else routing_decision.get("selected_model_rank")
        ),
        "selected_routing_tier": (
            llm_observability.get("selected_routing_tier")
            or routing_decision.get("selected_routing_tier")
        ),
        "routing_reason": routing_decision.get("routing_reason"),
        "quota_skip_count": metric_int(
            llm_observability.get("quota_skip_count")
            if llm_observability.get("quota_skip_count") is not None
            else routing_decision.get("quota_skip_count"),
            default=0,
        ),
        "daily_quota_skip_count": metric_int(
            llm_observability.get("daily_quota_skip_count")
            if llm_observability.get("daily_quota_skip_count") is not None
            else routing_decision.get("daily_quota_skip_count"),
            default=0,
        ),
        "cooldown_skip_count": metric_int(
            llm_observability.get("cooldown_skip_count")
            if llm_observability.get("cooldown_skip_count") is not None
            else routing_decision.get("cooldown_skip_count"),
            default=0,
        ),
        "degraded_from_primary": bool(
            llm_observability.get("degraded_from_primary")
            if llm_observability.get("degraded_from_primary") is not None
            else routing_decision.get("degraded_from_primary")
        ),
        "retrieval_strategy": retrieval_trace.get("strategy"),
        "retrieval_latency_ms": metric_float(
            retrieval_trace.get("duration_ms")
            if retrieval_trace.get("duration_ms") is not None
            else llm_observability.get("retrieval_latency_ms")
        ),
        "retrieval_candidate_count": metric_int(retrieval_trace.get("candidate_count")),
        "retrieval_returned_count": metric_int(retrieval_trace.get("returned_count")),
        "reranker_provider": (
            reranker_status.get("resolved_provider")
            or reranker_status.get("normalized_provider")
            or reranker_status.get("provider")
        ),
        "reranker_execution_mode": reranker_status.get("execution_mode"),
        "reranker_quality_tier": reranker_status.get("quality_tier"),
        "model_reranker_ready": bool(reranker_status.get("model_reranker_ready")),
        "keyword_fallback": bool(reranker_status.get("keyword_fallback")),
        "reranker_fallback_reason": (
            reranker_status.get("fallback_reason") or reranker_status.get("model_reranker_gap")
        ),
        "graph_reasoning_status": graph_reasoning.get("status"),
        "graph_reasoning_strategy": graph_reasoning.get("strategy"),
        "graph_reasoning_requested_ticker_count": metric_int(
            graph_reasoning.get("requested_ticker_count"),
            default=0,
        ),
        "graph_reasoning_covered_ticker_count": metric_int(
            graph_reasoning.get("covered_ticker_count"),
            default=0,
        ),
        "graph_reasoning_missing_ticker_count": metric_int(
            graph_reasoning.get("missing_ticker_count"),
            default=0,
        ),
        "graph_reasoning_path_count": metric_int(
            graph_reasoning.get("path_count"),
            default=0,
        ),
        "graph_reasoning_coverage_ratio": metric_float(
            graph_reasoning.get("coverage_ratio"),
            default=0.0,
        ),
        "graph_reasoning_max_paths": graph_reasoning.get("max_paths"),
        "trace_captured": bool(llm_observability or retrieval_trace or graph_reasoning),
    }


def report_execution_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("report_execution")
    if isinstance(direct, dict):
        return direct
    for key in ("rerun_report", "report_result"):
        nested = payload.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("report_execution"), dict):
            return nested["report_execution"]
    return {}


def report_observability_totals(rows: list[dict]) -> dict[str, Any]:
    latency_values = [
        row["llm_latency_ms"] for row in rows if row.get("llm_latency_ms") is not None
    ]
    retrieval_latency_values = [
        row["retrieval_latency_ms"] for row in rows if row.get("retrieval_latency_ms") is not None
    ]
    llm_latency = latency_distribution(latency_values)
    retrieval_latency = latency_distribution(retrieval_latency_values)
    return {
        "report_count": len(rows),
        "trace_captured_count": sum(1 for row in rows if row.get("trace_captured")),
        "trace_missing_count": sum(1 for row in rows if not row.get("trace_captured")),
        "total_token_estimate": sum(row.get("total_token_estimate") or 0 for row in rows),
        "estimated_cost_usd": round(sum(row.get("estimated_cost_usd") or 0.0 for row in rows), 6),
        "fallback_count": sum(1 for row in rows if row.get("fallback")),
        "fallback_path_count": sum(1 for row in rows if row.get("fallback_path_used")),
        "retryable_failure_count": sum(row.get("retryable_failure_count") or 0 for row in rows),
        "quota_skip_count": sum(row.get("quota_skip_count") or 0 for row in rows),
        "daily_quota_skip_count": sum(row.get("daily_quota_skip_count") or 0 for row in rows),
        "cooldown_skip_count": sum(row.get("cooldown_skip_count") or 0 for row in rows),
        "degraded_from_primary_count": sum(1 for row in rows if row.get("degraded_from_primary")),
        "retrieval_trace_count": sum(1 for row in rows if row.get("retrieval_strategy")),
        "model_reranker_ready_count": sum(1 for row in rows if row.get("model_reranker_ready")),
        "keyword_fallback_count": sum(1 for row in rows if row.get("keyword_fallback")),
        "graph_reasoning_ready_count": sum(
            1 for row in rows if row.get("graph_reasoning_status") == "ready"
        ),
        "graph_reasoning_missing_count": sum(
            1 for row in rows if row.get("graph_reasoning_status") != "ready"
        ),
        "graph_reasoning_partial_count": sum(
            1
            for row in rows
            if row.get("graph_reasoning_status") == "ready"
            and (
                (metric_int(row.get("graph_reasoning_missing_ticker_count"), default=0) or 0) > 0
                or (metric_int(row.get("graph_reasoning_path_count"), default=0) or 0) <= 0
            )
        ),
        "graph_reasoning_path_count": sum(
            row.get("graph_reasoning_path_count") or 0 for row in rows
        ),
        "graph_reasoning_covered_ticker_count": sum(
            row.get("graph_reasoning_covered_ticker_count") or 0 for row in rows
        ),
        "graph_reasoning_requested_ticker_count": sum(
            row.get("graph_reasoning_requested_ticker_count") or 0 for row in rows
        ),
        "graph_reasoning_coverage_ratio": _graph_reasoning_coverage_ratio(rows),
        "avg_llm_latency_ms": llm_latency["avg"],
        "p95_llm_latency_ms": llm_latency["p95"],
        "max_llm_latency_ms": llm_latency["max"],
        "avg_retrieval_latency_ms": retrieval_latency["avg"],
        "p95_retrieval_latency_ms": retrieval_latency["p95"],
        "max_retrieval_latency_ms": retrieval_latency["max"],
    }


def report_observability_status(rows: list[dict], totals: dict[str, Any]) -> str:
    if not rows:
        return "no_reports"
    if int(totals.get("trace_missing_count") or 0):
        return "caution"
    if int(totals.get("fallback_path_count") or 0) or int(
        totals.get("retryable_failure_count") or 0
    ):
        return "caution"
    return "ready"


def report_observability_alerts(
    rows: list[dict],
    totals: dict[str, Any],
) -> list[dict[str, str]]:
    alerts = []
    if rows and int(totals.get("trace_missing_count") or 0):
        alerts.append(
            {
                "severity": "warning",
                "code": "report_trace_missing",
                "message": "部分最新版報告缺少已儲存的 LLM/RAG 追蹤資料。",
            }
        )
    if int(totals.get("fallback_path_count") or 0):
        alerts.append(
            {
                "severity": "warning",
                "code": "report_llm_fallback_used",
                "message": "部分最新版報告使用模型降級路由。",
            }
        )
    if int(totals.get("retryable_failure_count") or 0):
        alerts.append(
            {
                "severity": "warning",
                "code": "report_llm_retryable_failures",
                "message": "最新版報告生成時出現可重試的 LLM 失敗。",
            }
        )
    if int(totals.get("keyword_fallback_count") or 0):
        alerts.append(
            {
                "severity": "info",
                "code": "report_reranker_keyword_fallback",
                "message": "部分最新版報告改用關鍵字排序後援。",
            }
        )
    if int(totals.get("graph_reasoning_missing_count") or 0):
        alerts.append(
            {
                "severity": "info",
                "code": "report_graphrag_reasoning_missing",
                "message": "部分最新版報告缺少 GraphRAG 推理追蹤。",
            }
        )
    if int(totals.get("graph_reasoning_partial_count") or 0):
        alerts.append(
            {
                "severity": "info",
                "code": "report_graphrag_reasoning_partial",
                "message": "部分最新版報告已有 GraphRAG 推理，但圖譜路徑覆蓋不完整。",
            }
        )
    return alerts[:10]


def _graph_reasoning_coverage_ratio(rows: list[dict]) -> float:
    requested = sum(row.get("graph_reasoning_requested_ticker_count") or 0 for row in rows)
    if requested <= 0:
        return 0.0
    covered = sum(row.get("graph_reasoning_covered_ticker_count") or 0 for row in rows)
    return round(covered / requested, 4)


__all__ = [
    "report_execution_from_payload",
    "report_observability_alerts",
    "report_observability_bottleneck_rows",
    "report_observability_recommendations",
    "report_observability_status",
    "report_observability_summary_row",
    "report_observability_totals",
]
