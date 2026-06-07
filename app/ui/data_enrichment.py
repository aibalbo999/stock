from __future__ import annotations

import streamlit as st

from app.services.whitelist import SupplyChainWhitelist
from app.ui.data_enrichment_manual import render_manual_ingest_tab
from app.ui.data_enrichment_market import render_market_data_tab
from app.ui.data_enrichment_rss import render_rss_ingest_tab
from app.ui.data_enrichment_runtime import company_filing_runtime_rows as _company_filing_runtime_rows


def company_filing_runtime_rows(service_snapshot: dict) -> list[dict]:
    return _company_filing_runtime_rows(service_snapshot)


def render_data_enrichment() -> None:
    whitelist = SupplyChainWhitelist()
    allowed_tickers = sorted(whitelist.allowed_tickers())
    data_tabs = st.tabs(["市場快取與刷新", "手動補充", "RSS 匯入"])

    with data_tabs[0]:
        render_market_data_tab(allowed_tickers)
    with data_tabs[1]:
        render_manual_ingest_tab(whitelist, allowed_tickers)
    with data_tabs[2]:
        render_rss_ingest_tab()
