from __future__ import annotations

from typing import Any

import streamlit as st

from app.services.whitelist import SupplyChainWhitelist
from app.ui.dashboard_core import render_section_header
from app.ui.system_settings_scope_view import scope_source_summary_html


def _whitelist_source_label(settings_whitelist: SupplyChainWhitelist) -> str:
    for attr_name in ("path", "source_path", "whitelist_path"):
        source_path = getattr(settings_whitelist, attr_name, None)
        if source_path:
            return str(source_path)

    raw = getattr(settings_whitelist, "raw", {})
    if isinstance(raw, dict):
        for key in ("source_path", "_source", "path"):
            source_path = raw.get(key)
            if source_path:
                return str(source_path)

    return "data/ai_supply_chain_whitelist.json"


def scope_source_summary(settings_whitelist: SupplyChainWhitelist) -> dict[str, str]:
    segments = list(getattr(settings_whitelist, "segments", []) or [])
    companies_fn = getattr(settings_whitelist, "companies", None)
    companies = list(companies_fn() if callable(companies_fn) else [])
    risk_keywords = list(getattr(settings_whitelist, "risk_keywords", []) or [])
    source_path = _whitelist_source_label(settings_whitelist)

    return {
        "state": "ready",
        "title": "系統靜態股票範圍",
        "detail": (
            f"目前可辨識 {len(companies)} 檔股票、{len(segments)} 個產業分類、"
            f"{len(risk_keywords)} 個風險詞組。"
        ),
        "source": f"來源：{source_path}",
        "next_step": (
            "本頁不是本次報告的動態候選名單；動態候選與採信狀態請在報告中心的生命週期查看。"
        ),
        "fallback_hint": (
            "若任務被白名單或輸入擋下，請先回分析工作區調整股票，或到維護頁查看任務診斷。"
        ),
    }


def _render_scope_source_summary(summary: dict[str, Any]) -> None:
    st.markdown(scope_source_summary_html(summary), unsafe_allow_html=True)


def render_scope_tab(settings_whitelist: SupplyChainWhitelist) -> None:
    render_section_header("股票範圍", "這裡是系統可辨識的台股公司範圍；正式報告仍會再用資料證據篩選。")
    _render_scope_source_summary(scope_source_summary(settings_whitelist))
    segments = settings_whitelist.segments
    scope_cols = st.columns(3)
    scope_cols[0].metric("產業分類", len(segments))
    scope_cols[1].metric("股票數", len(settings_whitelist.companies()))
    scope_cols[2].metric("風險詞組", len(settings_whitelist.risk_keywords))
    segment_filter = st.selectbox(
        "產業分類篩選",
        options=["全部"] + [segment.name for segment in segments],
    )
    segment_rows = []
    for segment in segments:
        if segment_filter != "全部" and segment.name != segment_filter:
            continue
        for company in segment.companies:
            segment_rows.append(
                {
                    "股票": company.ticker,
                    "公司": company.name,
                    "產業分類": segment.name,
                    "證據關鍵字": "、".join(company.evidence_keywords[:5]) or "-",
                }
            )
    if segment_rows:
        st.dataframe(segment_rows, width="stretch", hide_index=True)
    else:
        st.info("目前沒有符合篩選的公司。")
    with st.expander("進階：原始白名單 JSON"):
        st.json(settings_whitelist.raw)
