from __future__ import annotations

from typing import Any

import streamlit as st


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
    return [alert for alert in summary.get("alerts") or [] if isinstance(alert, dict)]


def report_observability_bottleneck_rows(summary: dict[str, Any]) -> list[dict]:
    return [row for row in summary.get("bottlenecks") or [] if isinstance(row, dict)]


def report_observability_recommendation_rows(summary: dict[str, Any]) -> list[dict]:
    return [row for row in summary.get("recommendations") or [] if isinstance(row, dict)]


def report_observability_report_rows(summary: dict[str, Any]) -> list[dict]:
    return [row for row in summary.get("reports") or [] if isinstance(row, dict)]


def render_report_observability_panel(report_observability_summary: dict[str, Any]) -> None:
    metrics = report_observability_metric_values(report_observability_summary)
    metric_cols = st.columns(len(metrics))
    for column, (label, value) in zip(metric_cols, metrics.items()):
        column.metric(label, value)

    for alert in report_observability_alert_rows(report_observability_summary):
        message = str(alert.get("message") or alert.get("code") or "")
        if alert.get("severity") == "warning":
            st.warning(message)
        elif alert.get("severity") == "error":
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
