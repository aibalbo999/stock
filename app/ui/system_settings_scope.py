from __future__ import annotations

import streamlit as st

from app.services.whitelist import SupplyChainWhitelist
from app.ui.dashboard_core import render_section_header


def render_scope_tab(settings_whitelist: SupplyChainWhitelist) -> None:
    render_section_header("股票範圍", "這裡是系統可辨識的台股公司範圍；正式報告仍會再用資料證據篩選。")
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
