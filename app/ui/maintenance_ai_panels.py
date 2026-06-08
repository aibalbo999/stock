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
        usage_totals = (
            llm_usage_summary.get("totals")
            if isinstance(llm_usage_summary.get("totals"), dict)
            else {}
        )
        usage_cols = st.columns(5)
        usage_cols[0].metric("7 日請求", int(usage_totals.get("request_count") or 0))
        usage_cols[1].metric("7 日 Token", int(usage_totals.get("total_token_estimate") or 0))
        usage_cols[2].metric(
            "估算成本 USD",
            f"{float(usage_totals.get('estimated_cost_usd') or 0.0):.4f}",
        )
        usage_cols[3].metric("Fallback 次數", int(usage_totals.get("fallback_path_count") or 0))
        usage_cols[4].metric("可重試失敗", int(usage_totals.get("retryable_failure_count") or 0))
        daily_usage_rows = llm_usage_summary.get("daily") or []
        model_usage_rows = llm_usage_summary.get("by_model") or []
        operation_usage_rows = llm_usage_summary.get("by_operation") or []
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


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
