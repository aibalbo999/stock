from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.data_enrichment_runtime import company_filing_visual_rag_model_chain_rows
from app.ui.llm_quota_panel import (
    llm_quota_captions,
    llm_quota_metric_values,
    llm_quota_model_rows,
)


def render_ai_quota_panel(llm_quota: dict, service_snapshot: dict) -> None:
    with st.expander("AI 額度與模型路由", expanded=True):
        quota_metrics = llm_quota_metric_values(llm_quota)
        quota_cols = st.columns(4)
        quota_cols[0].metric("推薦模型", quota_metrics["推薦模型"])
        quota_cols[1].metric("今日請求", quota_metrics["今日請求"])
        quota_cols[2].metric("今日 Token", quota_metrics["今日 Token"])
        quota_cols[3].metric("額度重置", quota_metrics["額度重置"])
        for caption in llm_quota_captions(llm_quota):
            st.caption(caption)
        quota_rows = llm_quota_model_rows(llm_quota)
        if quota_rows:
            st.dataframe(quota_rows, width="stretch", hide_index=True)
        else:
            st.info("尚未有 AI 用量紀錄。")
        visual_rag_chain_rows = company_filing_visual_rag_model_chain_rows(service_snapshot)
        if visual_rag_chain_rows:
            st.caption("Visual RAG / PDF 圖片解析模型鏈")
            st.dataframe(visual_rag_chain_rows, width="stretch", hide_index=True)


def render_ai_usage_panel(llm_usage_summary: dict) -> None:
    with st.expander("AI 用量趨勢與成本", expanded=True):
        usage_metrics = llm_usage_metric_values(llm_usage_summary)
        usage_cols = st.columns(len(usage_metrics))
        for column, (label, value) in zip(usage_cols, usage_metrics.items()):
            column.metric(label, value)
        daily_usage_rows = llm_usage_summary.get("daily") or []
        model_usage_rows = llm_usage_summary.get("by_model") or []
        operation_usage_rows = llm_usage_summary.get("by_operation") or []
        recent_routing_rows = llm_usage_recent_routing_rows(llm_usage_summary)
        if daily_usage_rows:
            st.caption("每日 token / request 趨勢")
            st.dataframe(daily_usage_rows, width="stretch", hide_index=True)
        if model_usage_rows:
            st.caption("模型用量")
            st.dataframe(model_usage_rows, width="stretch", hide_index=True)
        if operation_usage_rows:
            st.caption("任務用量")
            st.dataframe(operation_usage_rows, width="stretch", hide_index=True)
        routing_captions = llm_usage_routing_captions(llm_usage_summary)
        routing_rows = llm_usage_routing_rows(llm_usage_summary)
        if routing_captions or routing_rows:
            st.caption("模型路由實況")
            for caption in routing_captions:
                st.caption(caption)
            if routing_rows:
                st.dataframe(routing_rows, width="stretch", hide_index=True)
        if recent_routing_rows:
            st.caption("最近模型路由事件")
            st.dataframe(recent_routing_rows, width="stretch", hide_index=True)
        if not (daily_usage_rows or model_usage_rows or operation_usage_rows):
            st.info("尚未有可彙總的 AI 用量紀錄。")
        usage_alerts = llm_usage_summary.get("alerts") or []
        for alert in usage_alerts:
            message = str(alert.get("message") or alert.get("code") or "")
            if alert.get("severity") == "error":
                st.error(message)
            elif alert.get("severity") == "warning":
                st.warning(message)
            else:
                st.caption(message)
        cost_budget = llm_usage_summary.get("cost_budget")
        if isinstance(cost_budget, dict):
            st.caption(
                "成本預算："
                f"{cost_budget.get('status')}｜"
                f"window ${float(cost_budget.get('window_cost_budget_usd') or 0.0):.4f}"
            )


def llm_usage_metric_values(llm_usage_summary: dict) -> dict[str, str | int]:
    totals = _dict_value(llm_usage_summary.get("totals"))
    return {
        "7 日請求": int(totals.get("request_count") or 0),
        "7 日 Token": int(totals.get("total_token_estimate") or 0),
        "估算成本 USD": f"{float(totals.get('estimated_cost_usd') or 0.0):.4f}",
        "Fallback 次數": int(totals.get("fallback_path_count") or 0),
        "可重試失敗": int(totals.get("retryable_failure_count") or 0),
        "Quota skip": int(totals.get("quota_skip_count") or 0),
        "模型降級": int(totals.get("degraded_from_primary_count") or 0),
    }


def llm_usage_routing_captions(llm_usage_summary: dict) -> list[str]:
    routing = _dict_value(llm_usage_summary.get("routing_snapshot"))
    if not routing or routing.get("available") is False:
        reason = str(routing.get("reason") or "").strip()
        return [f"模型路由實況尚不可用：{reason}"] if reason else []
    captions = []
    recommended = str(routing.get("recommended_model") or "").strip()
    if recommended:
        parts = [f"目前推薦：{recommended}"]
        rank = routing.get("recommended_rank")
        if rank not in {None, ""}:
            parts.append(f"順位 {rank}")
        tier = str(routing.get("recommended_routing_tier") or "").strip()
        if tier:
            parts.append(f"tier={tier}")
        captions.append("｜".join(parts))
    recommended_reason = str(routing.get("recommended_reason") or "").strip()
    if recommended_reason:
        captions.append(recommended_reason)
    high_quota_models = [
        str(model).strip()
        for model in routing.get("high_quota_fallback_models") or []
        if str(model).strip()
    ]
    if high_quota_models:
        captions.append("高額度保底模型：" + "、".join(high_quota_models))
    return captions


def llm_usage_routing_rows(llm_usage_summary: dict) -> list[dict]:
    routing = _dict_value(llm_usage_summary.get("routing_snapshot"))
    rows = []
    for model in routing.get("models") or []:
        if not isinstance(model, dict):
            continue
        rows.append(
            {
                "rank": model.get("rank"),
                "model": model.get("model"),
                "status": model.get("status"),
                "tier": model.get("routing_tier"),
                "reason": model.get("status_reason"),
                "requests_used": model.get("requests_used"),
                "request_budget": model.get("request_budget"),
                "requests_remaining": model.get("requests_remaining"),
                "completion_count": model.get("completion_count"),
                "tokens_used": model.get("tokens_used"),
                "token_budget": model.get("token_budget"),
                "tokens_remaining": model.get("tokens_remaining"),
            }
        )
    return rows


def llm_usage_recent_routing_rows(llm_usage_summary: dict) -> list[dict]:
    rows = []
    for item in llm_usage_summary.get("recent") or []:
        if not isinstance(item, dict):
            continue
        quota_skips = int(item.get("quota_skip_count") or 0)
        degraded = bool(item.get("degraded_from_primary"))
        routing_reason = str(item.get("routing_reason") or "").strip()
        if not (quota_skips or degraded or routing_reason):
            continue
        rows.append(
            {
                "created_at": item.get("created_at"),
                "operation": item.get("operation"),
                "model": item.get("model"),
                "selected_rank": item.get("selected_model_rank"),
                "tier": item.get("selected_routing_tier"),
                "routing_reason": routing_reason or None,
                "quota_skip_count": quota_skips,
                "daily_quota_skip_count": int(item.get("daily_quota_skip_count") or 0),
                "cooldown_skip_count": int(item.get("cooldown_skip_count") or 0),
                "degraded_from_primary": degraded,
            }
        )
    return rows[-20:]


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
