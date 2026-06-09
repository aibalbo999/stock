from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.latency_metrics import latency_distribution


def report_observability_summary_row(
    snapshot: dict[str, Any],
    parse_run_payload_func: Callable[[str | None], dict],
) -> dict:
    payload = parse_run_payload_func(snapshot.get("run_payload"))
    execution = report_execution_from_payload(payload)
    llm = execution.get("llm") if isinstance(execution.get("llm"), dict) else {}
    llm_observability = (
        llm.get("observability")
        if isinstance(llm.get("observability"), dict)
        else {}
    )
    attempt_summary = (
        llm.get("attempt_summary")
        if isinstance(llm.get("attempt_summary"), dict)
        else {}
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
        "attempt_count": _metric_int(attempt_summary.get("attempt_count")),
        "retryable_failure_count": _metric_int(
            attempt_summary.get("retryable_failure_count"),
            default=0,
        ),
        "primary_failure_category": attempt_summary.get("primary_failure_category"),
        "llm_latency_ms": _metric_float(llm_observability.get("latency_ms")),
        "total_token_estimate": _metric_int(llm_observability.get("total_token_estimate")),
        "estimated_cost_usd": _metric_float(llm_observability.get("estimated_cost_usd")),
        "cost_tracking_mode": llm_observability.get("cost_tracking_mode"),
        "selected_model_rank": _metric_int(
            llm_observability.get("selected_model_rank")
            if llm_observability.get("selected_model_rank") is not None
            else routing_decision.get("selected_model_rank")
        ),
        "selected_routing_tier": (
            llm_observability.get("selected_routing_tier")
            or routing_decision.get("selected_routing_tier")
        ),
        "routing_reason": routing_decision.get("routing_reason"),
        "quota_skip_count": _metric_int(
            llm_observability.get("quota_skip_count")
            if llm_observability.get("quota_skip_count") is not None
            else routing_decision.get("quota_skip_count"),
            default=0,
        ),
        "daily_quota_skip_count": _metric_int(
            llm_observability.get("daily_quota_skip_count")
            if llm_observability.get("daily_quota_skip_count") is not None
            else routing_decision.get("daily_quota_skip_count"),
            default=0,
        ),
        "cooldown_skip_count": _metric_int(
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
        "retrieval_latency_ms": _metric_float(
            retrieval_trace.get("duration_ms")
            if retrieval_trace.get("duration_ms") is not None
            else llm_observability.get("retrieval_latency_ms")
        ),
        "retrieval_candidate_count": _metric_int(retrieval_trace.get("candidate_count")),
        "retrieval_returned_count": _metric_int(retrieval_trace.get("returned_count")),
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
            reranker_status.get("fallback_reason")
            or reranker_status.get("model_reranker_gap")
        ),
        "graph_reasoning_status": graph_reasoning.get("status"),
        "graph_reasoning_strategy": graph_reasoning.get("strategy"),
        "graph_reasoning_requested_ticker_count": _metric_int(
            graph_reasoning.get("requested_ticker_count"),
            default=0,
        ),
        "graph_reasoning_covered_ticker_count": _metric_int(
            graph_reasoning.get("covered_ticker_count"),
            default=0,
        ),
        "graph_reasoning_missing_ticker_count": _metric_int(
            graph_reasoning.get("missing_ticker_count"),
            default=0,
        ),
        "graph_reasoning_path_count": _metric_int(
            graph_reasoning.get("path_count"),
            default=0,
        ),
        "graph_reasoning_coverage_ratio": _metric_float(
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
    latency_values = [row["llm_latency_ms"] for row in rows if row.get("llm_latency_ms") is not None]
    retrieval_latency_values = [
        row["retrieval_latency_ms"]
        for row in rows
        if row.get("retrieval_latency_ms") is not None
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
                (_metric_int(row.get("graph_reasoning_missing_ticker_count"), default=0) or 0)
                > 0
                or (_metric_int(row.get("graph_reasoning_path_count"), default=0) or 0)
                <= 0
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


def report_observability_bottleneck_rows(
    rows: list[dict],
    limit: int = 10,
) -> list[dict[str, Any]]:
    bottlenecks = [
        row
        for row in (
            _observability_bottleneck_row(report_row) for report_row in rows
        )
        if row is not None
    ]
    return sorted(
        bottlenecks,
        key=lambda item: (-float(item["score"]), str(item.get("generated_at") or ""), int(item.get("id") or 0)),
    )[: max(1, min(int(limit or 10), 25))]


def report_observability_recommendations(
    rows: list[dict],
    totals: dict[str, Any],
    bottlenecks: list[dict],
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    recommendations = []
    top_bottleneck = bottlenecks[0] if bottlenecks else {}
    if int(totals.get("trace_missing_count") or 0):
        recommendations.append(
            _observability_recommendation(
                priority=10,
                severity="warning",
                code="trace_missing",
                affected_reports=int(totals.get("trace_missing_count") or 0),
                evidence=f"trace_missing={totals.get('trace_missing_count')}",
                next_action="重新產生缺 trace 的報告，並確認 run payload 寫入 report_execution。",
                top_bottleneck=top_bottleneck,
            )
        )
    fallback_count = int(totals.get("fallback_path_count") or 0)
    quota_skips = int(totals.get("quota_skip_count") or 0)
    degraded_count = int(totals.get("degraded_from_primary_count") or 0)
    if fallback_count or quota_skips or degraded_count:
        recommendations.append(
            _observability_recommendation(
                priority=20,
                severity="warning",
                code="llm_quota_routing",
                affected_reports=max(fallback_count, degraded_count, 1),
                evidence=(
                    f"fallback={fallback_count}; quota_skips={quota_skips}; "
                    f"degraded={degraded_count}"
                ),
                next_action=(
                    "先看 /llm/quota 的 exhausted/cooldown 模型；確認聰明模型仍在前，"
                    "只有 429/quota 後才降級。"
                ),
                top_bottleneck=top_bottleneck,
            )
        )
    retryable_failures = int(totals.get("retryable_failure_count") or 0)
    if retryable_failures:
        recommendations.append(
            _observability_recommendation(
                priority=30,
                severity="warning",
                code="llm_retryable_failures",
                affected_reports=retryable_failures,
                evidence=f"retryable_failures={retryable_failures}",
                next_action="檢查 LLM provider timeout/429/5xx 分布，必要時拉長 cooldown 或降低同時產報。",
                top_bottleneck=top_bottleneck,
            )
        )
    keyword_fallback = int(totals.get("keyword_fallback_count") or 0)
    if keyword_fallback:
        recommendations.append(
            _observability_recommendation(
                priority=40,
                severity="info",
                code="reranker_model_fallback",
                affected_reports=keyword_fallback,
                evidence=f"keyword_fallback={keyword_fallback}",
                next_action="啟用本機 cross-encoder、Cohere 或 LLM reranker，降低只靠關鍵字排序的風險。",
                top_bottleneck=top_bottleneck,
            )
        )
    graph_missing = int(totals.get("graph_reasoning_missing_count") or 0)
    graph_partial = int(totals.get("graph_reasoning_partial_count") or 0)
    if graph_missing or graph_partial:
        recommendations.append(
            _observability_recommendation(
                priority=45,
                severity="info",
                code="graphrag_reasoning_coverage",
                affected_reports=max(graph_missing + graph_partial, 1),
                evidence=(
                    f"missing_trace={graph_missing}; partial_or_zero_path={graph_partial}; "
                    f"coverage={totals.get('graph_reasoning_coverage_ratio')}"
                ),
                next_action=(
                    "檢查候選白名單 segment/ticker mapping 與 GraphRAG taxonomy；"
                    "缺路徑的股票先補同業/上下游 edge，再重產報告。"
                ),
                top_bottleneck=top_bottleneck,
            )
        )
    p95_llm_latency = _metric_float(totals.get("p95_llm_latency_ms"), default=0.0) or 0.0
    if p95_llm_latency >= 5000:
        recommendations.append(
            _observability_recommendation(
                priority=50,
                severity="info",
                code="llm_latency",
                affected_reports=_count_rows_at_or_above(rows, "llm_latency_ms", 5000),
                evidence=f"p95_llm_latency_ms={p95_llm_latency}",
                next_action="檢查 prompt 長度、模型選擇與 retry 次數；低風險章節可改走較快 fallback。",
                top_bottleneck=top_bottleneck,
            )
        )
    p95_retrieval_latency = (
        _metric_float(totals.get("p95_retrieval_latency_ms"), default=0.0) or 0.0
    )
    if p95_retrieval_latency >= 1000:
        recommendations.append(
            _observability_recommendation(
                priority=60,
                severity="info",
                code="retrieval_latency",
                affected_reports=_count_rows_at_or_above(
                    rows,
                    "retrieval_latency_ms",
                    1000,
                ),
                evidence=f"p95_retrieval_latency_ms={p95_retrieval_latency}",
                next_action="檢查 Chroma query、hybrid candidate limit 與 rerank top-k，避免檢索拖慢報告。",
                top_bottleneck=top_bottleneck,
            )
        )
    max_tokens = max((_metric_int(row.get("total_token_estimate"), default=0) or 0) for row in rows)
    if max_tokens >= 12000:
        recommendations.append(
            _observability_recommendation(
                priority=70,
                severity="info",
                code="token_volume",
                affected_reports=sum(
                    1
                    for row in rows
                    if (_metric_int(row.get("total_token_estimate"), default=0) or 0) >= 12000
                ),
                evidence=f"max_tokens={max_tokens}",
                next_action="壓縮 RAG context、表格摘要與章節輸入，減少免費額度消耗。",
                top_bottleneck=top_bottleneck,
            )
        )
    estimated_cost = _metric_float(totals.get("estimated_cost_usd"), default=0.0) or 0.0
    if estimated_cost >= 0.05:
        recommendations.append(
            _observability_recommendation(
                priority=80,
                severity="info",
                code="estimated_cost",
                affected_reports=sum(1 for row in rows if row.get("estimated_cost_usd")),
                evidence=f"estimated_cost_usd={estimated_cost}",
                next_action="檢查 rate card 與模型任務分流；低風險摘要可交給 Flash-Lite/Gemma。",
                top_bottleneck=top_bottleneck,
            )
        )
    return sorted(recommendations, key=lambda item: int(item["priority"]))[: max(1, min(int(limit or 8), 20))]


def report_observability_status(rows: list[dict], totals: dict[str, Any]) -> str:
    if not rows:
        return "no_reports"
    if int(totals.get("trace_missing_count") or 0):
        return "caution"
    if int(totals.get("fallback_path_count") or 0) or int(totals.get("retryable_failure_count") or 0):
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
                "message": "Some latest reports do not have stored LLM/RAG trace payloads.",
            }
        )
    if int(totals.get("fallback_path_count") or 0):
        alerts.append(
            {
                "severity": "warning",
                "code": "report_llm_fallback_used",
                "message": "Some latest reports used LLM fallback routing.",
            }
        )
    if int(totals.get("retryable_failure_count") or 0):
        alerts.append(
            {
                "severity": "warning",
                "code": "report_llm_retryable_failures",
                "message": "Retryable LLM failures were observed during latest report generation.",
            }
        )
    if int(totals.get("keyword_fallback_count") or 0):
        alerts.append(
            {
                "severity": "info",
                "code": "report_reranker_keyword_fallback",
                "message": "Some latest reports used keyword reranking instead of a model/API reranker.",
            }
        )
    if int(totals.get("graph_reasoning_missing_count") or 0):
        alerts.append(
            {
                "severity": "info",
                "code": "report_graphrag_reasoning_missing",
                "message": "Some latest reports do not have GraphRAG reasoning trace.",
            }
        )
    if int(totals.get("graph_reasoning_partial_count") or 0):
        alerts.append(
            {
                "severity": "info",
                "code": "report_graphrag_reasoning_partial",
                "message": (
                    "Some latest reports have GraphRAG reasoning but incomplete graph "
                    "path coverage."
                ),
            }
        )
    return alerts[:10]


def _graph_reasoning_coverage_ratio(rows: list[dict]) -> float:
    requested = sum(row.get("graph_reasoning_requested_ticker_count") or 0 for row in rows)
    if requested <= 0:
        return 0.0
    covered = sum(row.get("graph_reasoning_covered_ticker_count") or 0 for row in rows)
    return round(covered / requested, 4)


def _observability_bottleneck_row(row: dict) -> dict[str, Any] | None:
    components = _observability_bottleneck_components(row)
    if not components:
        return None
    dominant_factor = max(components, key=components.get)
    reasons = _observability_bottleneck_reasons(row)
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "topic": row.get("topic"),
        "generated_at": row.get("generated_at"),
        "score": round(sum(components.values()), 2),
        "dominant_factor": dominant_factor,
        "severity": _observability_bottleneck_severity(row, dominant_factor),
        "next_action": _observability_bottleneck_next_action(row, dominant_factor),
        "reasons": "；".join(reasons),
        "model": row.get("model"),
        "llm_latency_ms": row.get("llm_latency_ms"),
        "retrieval_latency_ms": row.get("retrieval_latency_ms"),
        "total_token_estimate": row.get("total_token_estimate"),
        "estimated_cost_usd": row.get("estimated_cost_usd"),
    }


def _observability_bottleneck_components(row: dict) -> dict[str, float]:
    components: dict[str, float] = {}
    if not row.get("trace_captured"):
        components["trace_missing"] = 80.0
    if row.get("fallback_path_used"):
        components["llm_fallback"] = 40.0
    retryable_failures = _metric_int(row.get("retryable_failure_count"), default=0) or 0
    if retryable_failures:
        components["retryable_failures"] = min(30.0, float(retryable_failures) * 10.0)
    quota_skips = _metric_int(row.get("quota_skip_count"), default=0) or 0
    if quota_skips:
        components["quota_routing_skip"] = min(15.0, float(quota_skips) * 5.0)
    if row.get("keyword_fallback"):
        components["keyword_reranker_fallback"] = 12.0
    llm_latency_ms = _metric_float(row.get("llm_latency_ms"))
    if llm_latency_ms is not None and llm_latency_ms > 0:
        components["llm_latency"] = min(35.0, llm_latency_ms / 1000.0)
    retrieval_latency_ms = _metric_float(row.get("retrieval_latency_ms"))
    if retrieval_latency_ms is not None and retrieval_latency_ms > 0:
        components["retrieval_latency"] = min(20.0, retrieval_latency_ms / 100.0)
    total_tokens = _metric_int(row.get("total_token_estimate"), default=0) or 0
    if total_tokens:
        components["token_volume"] = min(25.0, total_tokens / 2000.0)
    estimated_cost = _metric_float(row.get("estimated_cost_usd"), default=0.0) or 0.0
    if estimated_cost:
        components["estimated_cost"] = min(30.0, estimated_cost * 1000.0)
    return components


def _observability_bottleneck_reasons(row: dict) -> list[str]:
    reasons: list[str] = []
    if not row.get("trace_captured"):
        reasons.append("trace_missing")
    if row.get("fallback_path_used"):
        reasons.append("llm_fallback")
    retryable_failures = _metric_int(row.get("retryable_failure_count"), default=0) or 0
    if retryable_failures:
        reasons.append(f"retryable_failures={retryable_failures}")
    quota_skips = _metric_int(row.get("quota_skip_count"), default=0) or 0
    if quota_skips:
        reasons.append(f"quota_skips={quota_skips}")
    if row.get("routing_reason"):
        reasons.append(f"routing_reason={row['routing_reason']}")
    if row.get("keyword_fallback"):
        reasons.append("keyword_reranker_fallback")
    if row.get("llm_latency_ms") is not None:
        reasons.append(f"llm_latency_ms={row['llm_latency_ms']}")
    if row.get("retrieval_latency_ms") is not None:
        reasons.append(f"retrieval_latency_ms={row['retrieval_latency_ms']}")
    if row.get("total_token_estimate"):
        reasons.append(f"tokens={row['total_token_estimate']}")
    if row.get("estimated_cost_usd"):
        reasons.append(f"cost_usd={row['estimated_cost_usd']}")
    return reasons


def _observability_bottleneck_severity(row: dict, dominant_factor: str) -> str:
    if dominant_factor == "trace_missing":
        return "warning"
    if row.get("fallback_path_used") or _metric_int(row.get("retryable_failure_count"), default=0):
        return "warning"
    return "info"


def _observability_bottleneck_next_action(row: dict, dominant_factor: str) -> str:
    if dominant_factor == "trace_missing":
        return "重新產生或檢查 run payload 是否寫入 report_execution trace。"
    if dominant_factor in {"llm_fallback", "retryable_failures"}:
        return "檢查 quota/routing、429 cooldown 與模型順序，避免每份報告先撞耗盡模型。"
    if dominant_factor == "quota_routing_skip":
        return "檢查今日模型額度與 cooldown；若為預期降級，確認高額度 fallback 排在聰明模型之後。"
    if dominant_factor == "keyword_reranker_fallback":
        return "啟用 cross-encoder、Cohere 或 LLM reranker，降低關鍵字 fallback 排序風險。"
    if dominant_factor == "retrieval_latency":
        return "檢查 vector store 查詢、hybrid candidate 數量與 rerank top-k。"
    if dominant_factor == "token_volume":
        return "壓縮 prompt、RAG context 或報告章節輸入，降低免費額度消耗。"
    if dominant_factor == "estimated_cost":
        return "確認 rate card、模型路由與是否可用 Flash-Lite/Gemma 承接低風險任務。"
    return "檢查 LLM latency、prompt 長度與模型 fallback 設定。"


def _observability_recommendation(
    *,
    priority: int,
    severity: str,
    code: str,
    affected_reports: int,
    evidence: str,
    next_action: str,
    top_bottleneck: dict,
) -> dict[str, Any]:
    return {
        "priority": priority,
        "severity": severity,
        "code": code,
        "affected_reports": max(0, int(affected_reports or 0)),
        "evidence": evidence,
        "next_action": next_action,
        "top_report_id": top_bottleneck.get("id"),
        "top_topic": top_bottleneck.get("topic"),
        "top_dominant_factor": top_bottleneck.get("dominant_factor"),
        "top_score": top_bottleneck.get("score"),
    }


def _count_rows_at_or_above(rows: list[dict], key: str, threshold: float) -> int:
    return sum(
        1
        for row in rows
        if (_metric_float(row.get(key), default=0.0) or 0.0) >= threshold
    )


def _metric_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _metric_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "report_execution_from_payload",
    "report_observability_alerts",
    "report_observability_bottleneck_rows",
    "report_observability_recommendations",
    "report_observability_status",
    "report_observability_summary_row",
    "report_observability_totals",
]
