from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.data_enrichment_market_presenter import market_cache_operator_summary
from app.ui.data_enrichment_market_view import market_cache_operator_summary_html


def render_market_cache_panel(allowed_tickers: list[str]) -> None:
    cache_summary = load_api_json_or_default(
        "/market/cache-summary?tickers=" + ",".join(allowed_tickers),
        {
            "market_snapshots": [],
            "valuations": [],
            "company_filings": [],
            "financial_metric_count": 0,
        },
        error_message="讀取市場快取失敗",
    )
    render_market_cache_operator_summary(cache_summary)
    cached_snapshots = cache_summary.get("market_snapshots") or []
    cached_valuations = cache_summary.get("valuations") or []
    cached_filings = cache_summary.get("company_filings") or []
    cached_financial_count = cache_summary.get("financial_metric_count") or 0

    cache_tabs = st.tabs(["股價快取", "估值快取", "公司文件"])
    with cache_tabs[0]:
        if cached_snapshots:
            st.dataframe(
                [
                    {
                        "股票": snapshot.get("ticker"),
                        "交易日": snapshot.get("trade_date"),
                        "收盤價": snapshot.get("close"),
                        "漲跌": snapshot.get("spread"),
                        "成交量": snapshot.get("trading_volume"),
                        "來源": snapshot.get("source"),
                        "更新時間 UTC": snapshot.get("fetched_at"),
                    }
                    for snapshot in cached_snapshots
                    if isinstance(snapshot, dict)
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("尚無市場資料快取。")
        st.caption(f"目前財報三表科目快取：{cached_financial_count} 筆")
    with cache_tabs[1]:
        if cached_valuations:
            st.dataframe(
                [
                    {
                        "股票": valuation.get("ticker"),
                        "交易日": valuation.get("trade_date"),
                        "本益比": valuation.get("pe_ratio"),
                        "股價淨值比": valuation.get("pb_ratio"),
                        "殖利率": valuation.get("dividend_yield"),
                        "來源": valuation.get("source"),
                        "更新時間 UTC": valuation.get("fetched_at"),
                    }
                    for valuation in cached_valuations
                    if isinstance(valuation, dict)
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("尚無估值資料快取。")
    with cache_tabs[2]:
        if cached_filings:
            st.dataframe(
                [
                    {
                        "股票": filing.get("ticker"),
                        "類型": filing.get("document_type"),
                        "標題": filing.get("title"),
                        "來源": filing.get("publisher"),
                        "日期": filing.get("published_at"),
                    }
                    for filing in cached_filings
                    if isinstance(filing, dict)
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("尚無公司文件快取。")


def render_market_cache_operator_summary(cache_summary: dict) -> None:
    rows = market_cache_operator_summary(cache_summary if isinstance(cache_summary, dict) else {})
    st.markdown(market_cache_operator_summary_html(rows), unsafe_allow_html=True)
