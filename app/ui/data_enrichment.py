from __future__ import annotations

import streamlit as st

from app.services.whitelist import SupplyChainWhitelist
from app.ui.data_enrichment_common import render_allowlist_scope_summary
from app.ui.data_enrichment_manual import render_manual_ingest_tab
from app.ui.data_enrichment_market import render_market_data_tab
from app.ui.data_enrichment_rss import render_rss_ingest_tab
from app.ui.data_enrichment_runtime import (
    company_filing_runtime_rows as _company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows as _company_filing_visual_rag_model_chain_rows,
)


DATA_ENRICHMENT_SECTION_LABELS = {
    "market": "市場快取與刷新",
    "manual": "手動補充",
    "rss": "RSS 匯入",
}


def company_filing_runtime_rows(service_snapshot: dict) -> list[dict]:
    return _company_filing_runtime_rows(service_snapshot)


def company_filing_visual_rag_model_chain_rows(service_snapshot: dict) -> list[dict]:
    return _company_filing_visual_rag_model_chain_rows(service_snapshot)


def render_data_enrichment() -> None:
    whitelist = SupplyChainWhitelist()
    allowed_tickers = sorted(whitelist.allowed_tickers())
    _apply_pending_data_enrichment_section()
    render_allowlist_scope_summary(whitelist, allowed_tickers)
    section = st.radio(
        "資料補強區塊",
        options=list(DATA_ENRICHMENT_SECTION_LABELS),
        format_func=data_enrichment_section_label,
        horizontal=True,
        key="data_enrichment_section",
        label_visibility="collapsed",
    )

    if section == "market":
        render_market_data_tab(allowed_tickers)
    elif section == "manual":
        render_manual_ingest_tab(whitelist, allowed_tickers)
    else:
        render_rss_ingest_tab()


def data_enrichment_section_label(section: str) -> str:
    return DATA_ENRICHMENT_SECTION_LABELS.get(section, section)


def _apply_pending_data_enrichment_section() -> None:
    pending_section = st.session_state.pop("pending_data_enrichment_section", None)
    if pending_section in DATA_ENRICHMENT_SECTION_LABELS:
        st.session_state["data_enrichment_section"] = pending_section
        return
    if st.session_state.get("data_enrichment_section") not in DATA_ENRICHMENT_SECTION_LABELS:
        st.session_state["data_enrichment_section"] = "market"
