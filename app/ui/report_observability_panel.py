from __future__ import annotations

from typing import Any

import streamlit as st


SEVERITY_LABELS = {
    "warning": "警告",
    "warn": "警告",
    "error": "錯誤",
    "info": "資訊",
}

BOTTLENECK_LABELS = {
    "trace_missing": "缺少追蹤資料",
    "llm_fallback": "模型降級",
    "retryable_failures": "可重試失敗",
    "quota_routing_skip": "額度路由略過",
    "keyword_reranker_fallback": "關鍵字 reranker 後援",
    "llm_latency": "LLM 延遲",
    "retrieval_latency": "檢索延遲",
    "token_volume": "Token 量過高",
    "estimated_cost": "成本偏高",
}

RECOMMENDATION_LABELS = {
    "trace_missing": "補齊報告追蹤資料",
    "llm_quota_routing": "模型額度與降級路由",
    "llm_retryable_failures": "LLM 可重試失敗",
    "reranker_model_fallback": "Reranker 模型後援",
    "graphrag_reasoning_coverage": "GraphRAG 推理覆蓋",
    "llm_latency": "LLM 延遲",
    "retrieval_latency": "檢索延遲",
    "token_volume": "Token 量過高",
    "estimated_cost": "成本偏高",
}

ALERT_MESSAGES = {
    "report_trace_missing": "部分最新版報告缺少 LLM/RAG 追蹤資料。",
    "report_llm_fallback_used": "部分最新版報告使用模型降級路由。",
    "report_llm_retryable_failures": "最新版報告生成時出現可重試的 LLM 失敗。",
    "report_reranker_keyword_fallback": "部分最新版報告改用關鍵字排序後援。",
    "report_graphrag_reasoning_missing": "部分最新版報告缺少 GraphRAG 推理追蹤。",
    "report_graphrag_reasoning_partial": "部分最新版報告的圖譜推理路徑覆蓋不完整。",
}

ALERT_NEXT_STEPS = {
    "report_trace_missing": "重新產生缺追蹤的報告，並確認 run payload 有寫入 report_execution。",
    "report_llm_fallback_used": (
        "檢查今日模型額度、冷卻與模型順序；確認聰明模型額度用完後才降級。"
    ),
    "report_llm_retryable_failures": "檢查 provider timeout、429 或 5xx 分布，必要時拉長 cooldown。",
    "report_reranker_keyword_fallback": "啟用本機 cross-encoder、Cohere 或 LLM reranker，降低排序風險。",
    "report_graphrag_reasoning_missing": "檢查 GraphRAG trace 是否寫入，並重產需要上下游推理的報告。",
    "report_graphrag_reasoning_partial": "補齊缺路徑股票的同業/上下游 edge，再重產報告。",
}

EVIDENCE_LABELS = {
    "fallback": "後援",
    "fallbacks": "後援",
    "quota_skip": "額度略過",
    "quota_skips": "額度略過",
    "degraded": "模型降級",
    "degraded_from_primary": "模型降級",
    "keyword_fallback": "關鍵字後援",
    "keyword_fallbacks": "關鍵字後援",
    "retryable_failure": "可重試失敗",
    "retryable_failures": "可重試失敗",
}

ACTION_TEXT_REPLACEMENTS = {
    "smart model": "聰明模型",
    "fallback": "後援",
    "cooldown": "冷卻",
}


def report_observability_metric_values(summary: dict[str, Any]) -> dict[str, object]:
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    return {
        "狀態": summary.get("status") or "-",
        "最新版報告": int(totals.get("report_count") or 0),
        "追蹤覆蓋": int(totals.get("trace_captured_count") or 0),
        "圖譜推理路徑": int(totals.get("graph_reasoning_path_count") or 0),
        "圖譜推理覆蓋率": _ratio_percent(
            totals.get("graph_reasoning_coverage_ratio")
        ),
        "平均 LLM 延遲 ms": totals.get("avg_llm_latency_ms") or "-",
        "P95 LLM 延遲 ms": totals.get("p95_llm_latency_ms") or "-",
        "P95 檢索延遲 ms": totals.get("p95_retrieval_latency_ms") or "-",
        "關鍵字後援": int(totals.get("keyword_fallback_count") or 0),
        "額度略過": int(totals.get("quota_skip_count") or 0),
        "模型降級": int(totals.get("degraded_from_primary_count") or 0),
    }


def _ratio_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "-"


def report_observability_alert_rows(summary: dict[str, Any]) -> list[dict]:
    return [
        {
            "嚴重度": _severity_label(alert.get("severity")),
            "提醒": _observability_alert_message(alert),
            "下一步": _observability_alert_next_step(alert),
        }
        for alert in summary.get("alerts") or []
        if isinstance(alert, dict)
    ]


def report_observability_bottleneck_rows(summary: dict[str, Any]) -> list[dict]:
    return [
        {
            "報告": _report_ref(row),
            "主題": row.get("topic") or "-",
            "嚴重度": _severity_label(row.get("severity")),
            "主要瓶頸": _observability_bottleneck_label(row.get("dominant_factor")),
            "分數": row.get("score") or "-",
            "原因": _observability_reason_text(row.get("reasons")),
            "下一步": row.get("next_action") or "-",
        }
        for row in summary.get("bottlenecks") or []
        if isinstance(row, dict)
    ]


def report_observability_recommendation_rows(summary: dict[str, Any]) -> list[dict]:
    return [
        {
            "優先順序": row.get("priority") or "-",
            "嚴重度": _severity_label(row.get("severity")),
            "建議": _observability_recommendation_label(row.get("code")),
            "影響": _affected_reports_text(row.get("affected_reports")),
            "關聯報告": _report_ref(row, key="top_report_id"),
            "主要瓶頸": _observability_bottleneck_label(row.get("top_dominant_factor")),
            "證據": _observability_evidence_text(row.get("evidence")),
            "下一步": _operator_action_text(row.get("next_action")),
        }
        for row in summary.get("recommendations") or []
        if isinstance(row, dict)
    ]


def report_observability_report_rows(summary: dict[str, Any]) -> list[dict]:
    return [
        {
            "報告": _report_ref(row),
            "主題": row.get("topic") or "-",
            "模型": row.get("model") or "-",
            "LLM 延遲 ms": row.get("llm_latency_ms") or "-",
            "檢索延遲 ms": row.get("retrieval_latency_ms") or "-",
            "Token 估算": row.get("total_token_estimate") or "-",
            "估算成本 USD": row.get("estimated_cost_usd") or "-",
            "模型降級": _yes_no(row.get("degraded_from_primary")),
            "關鍵字後援": _yes_no(row.get("keyword_fallback")),
            "圖譜推理路徑": int(row.get("graph_reasoning_path_count") or 0),
            "圖譜推理覆蓋率": _ratio_percent(row.get("graph_reasoning_coverage_ratio")),
        }
        for row in summary.get("reports") or []
        if isinstance(row, dict)
    ]


def _report_ref(row: dict[str, Any], *, key: str = "id") -> str:
    report_id = row.get(key) or row.get("report_id")
    return f"#{report_id}" if report_id else "-"


def _severity_label(value: Any) -> str:
    text = str(value or "").strip()
    return SEVERITY_LABELS.get(text, text or "-")


def _observability_bottleneck_label(value: Any) -> str:
    text = str(value or "").strip()
    return BOTTLENECK_LABELS.get(text, text or "-")


def _observability_recommendation_label(value: Any) -> str:
    text = str(value or "").strip()
    return RECOMMENDATION_LABELS.get(text, text or "-")


def _observability_alert_message(alert: dict[str, Any]) -> str:
    code = str(alert.get("code") or "").strip()
    if code in ALERT_MESSAGES:
        return ALERT_MESSAGES[code]
    message = str(alert.get("message") or "").strip()
    return message or "報告觀測需要檢查。"


def _observability_alert_next_step(alert: dict[str, Any]) -> str:
    code = str(alert.get("code") or "").strip()
    if code in ALERT_NEXT_STEPS:
        return _operator_action_text(ALERT_NEXT_STEPS[code])
    return "查看建議處理順序與優先優化清單。"


def _affected_reports_text(value: Any) -> str:
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        count = 0
    return f"{count} 份報告"


def _yes_no(value: Any) -> str:
    return "是" if bool(value) else "否"


def _observability_reason_text(value: Any) -> str:
    reasons = _split_observability_parts(value)
    labels = [_observability_reason_label(reason) for reason in reasons]
    return "；".join(label for label in labels if label) or "-"


def _observability_reason_label(reason: str) -> str:
    if reason.startswith("llm_latency_ms="):
        return f"LLM 延遲 {reason.split('=', 1)[1]} ms"
    if reason.startswith("retrieval_latency_ms="):
        return f"檢索延遲 {reason.split('=', 1)[1]} ms"
    if reason.startswith("quota_skips="):
        return f"額度略過 {reason.split('=', 1)[1]} 次"
    if reason.startswith("retryable_failures="):
        return f"可重試失敗 {reason.split('=', 1)[1]} 次"
    if reason.startswith("tokens="):
        return f"Token 估算 {reason.split('=', 1)[1]}"
    if reason.startswith("cost_usd="):
        return f"估算成本 USD {reason.split('=', 1)[1]}"
    if reason.startswith("routing_reason="):
        routing_reason = reason.split("=", 1)[1]
        return f"路由原因 {routing_reason}"
    return BOTTLENECK_LABELS.get(reason, reason)


def _observability_evidence_text(value: Any) -> str:
    evidence_parts = _split_observability_parts(value)
    labels = [_observability_evidence_label(part) for part in evidence_parts]
    return "；".join(label for label in labels if label) or "-"


def _observability_evidence_label(evidence: str) -> str:
    if "=" not in evidence:
        return EVIDENCE_LABELS.get(evidence, BOTTLENECK_LABELS.get(evidence, evidence))
    key, value = [part.strip() for part in evidence.split("=", 1)]
    label = EVIDENCE_LABELS.get(key)
    if label:
        return f"{label} {_format_count(value)}"
    if key in {"llm_latency_ms", "retrieval_latency_ms"}:
        return _observability_reason_label(evidence)
    if key in {"tokens", "total_token_estimate"}:
        return f"Token 估算 {value}"
    if key in {"cost_usd", "estimated_cost_usd"}:
        return f"估算成本 USD {value}"
    if key == "routing_reason":
        return f"路由原因 {_operator_action_text(value)}"
    return f"{key} {value}"


def _format_count(value: str) -> str:
    return f"{value} 次"


def _operator_action_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    for raw, label in ACTION_TEXT_REPLACEMENTS.items():
        text = text.replace(raw, label)
    for label in ACTION_TEXT_REPLACEMENTS.values():
        text = text.replace(f" {label} ", label)
        text = text.replace(f" {label}", label)
        text = text.replace(f"{label} ", label)
    return text


def _split_observability_parts(value: Any) -> list[str]:
    text = str(value or "").replace("；", ";")
    return [part.strip() for part in text.split(";") if part.strip()]


def render_report_observability_panel(report_observability_summary: dict[str, Any]) -> None:
    metrics = report_observability_metric_values(report_observability_summary)
    metric_cols = st.columns(len(metrics))
    for column, (label, value) in zip(metric_cols, metrics.items()):
        column.metric(label, value)

    for alert in report_observability_alert_rows(report_observability_summary):
        message = f"{alert.get('提醒', '')} 下一步：{alert.get('下一步', '')}"
        if alert.get("嚴重度") == "警告":
            st.warning(message)
        elif alert.get("嚴重度") == "錯誤":
            st.error(message)
        else:
            st.info(message)

    recommendation_rows = report_observability_recommendation_rows(report_observability_summary)
    if recommendation_rows:
        st.caption("建議處理順序")
        st.dataframe(recommendation_rows, width="stretch", hide_index=True)

    bottleneck_rows = report_observability_bottleneck_rows(report_observability_summary)
    if bottleneck_rows:
        st.caption("優先優化清單")
        st.dataframe(bottleneck_rows, width="stretch", hide_index=True)

    report_rows = report_observability_report_rows(report_observability_summary)
    if report_rows:
        st.dataframe(report_rows, width="stretch", hide_index=True)
    else:
        st.info("尚未有可彙總的報告生成觀測資料。")
