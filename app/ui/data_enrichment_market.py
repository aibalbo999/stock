from __future__ import annotations

from datetime import timedelta

import streamlit as st

from app.core.time import today_taipei
from app.ui.api_client import (
    API_TASK_PREFLIGHT_TIMEOUT_SECONDS,
    task_payload_dates,
)
from app.ui.api_loaders import load_api_json_or_default
from app.ui.background_tasks import submit_data_operation_task
from app.ui.dashboard_core import render_section_header
from app.ui.data_enrichment_common import (
    DATA_TASK_STATUS_STATE_KEYS,
    render_last_data_task_status,
)
from app.ui.data_enrichment_runtime import (
    company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows,
)


def render_market_data_tab(allowed_tickers: list[str]) -> None:
    render_section_header(
        "市場資料", "刷新股價、五年財報與估值資料；這些資料會影響品質門檻與投資行動限制。"
    )
    status_snapshot = load_api_json_or_default(
        "/db/status",
        {"tables": {}},
        error_message="讀取資料庫狀態失敗",
    )
    table_counts = status_snapshot.get("tables", {})
    count_cols = st.columns(5)
    count_cols[0].metric(
        "股價快取", table_counts.get("stock_price_snapshots", {}).get("count") or 0
    )
    count_cols[1].metric(
        "月營收快取", table_counts.get("monthly_revenue_snapshots", {}).get("count") or 0
    )
    count_cols[2].metric(
        "財報三表快取", table_counts.get("financial_metric_snapshots", {}).get("count") or 0
    )
    count_cols[3].metric(
        "估值快取", table_counts.get("valuation_metric_snapshots", {}).get("count") or 0
    )
    count_cols[4].metric("公司文件", table_counts.get("company_filings", {}).get("count") or 0)

    service_snapshot = load_api_json_or_default(
        "/services/status",
        {},
        error_message="讀取公司文件能力狀態失敗",
        timeout=API_TASK_PREFLIGHT_TIMEOUT_SECONDS,
    )
    runtime_rows = company_filing_runtime_rows(service_snapshot)
    visual_rag_chain_rows = company_filing_visual_rag_model_chain_rows(service_snapshot)
    if runtime_rows:
        with st.expander("公司文件補抓能力", expanded=False):
            st.dataframe(runtime_rows, width="stretch", hide_index=True)
            if visual_rag_chain_rows:
                st.caption("Visual RAG 模型鏈")
                st.dataframe(visual_rag_chain_rows, width="stretch", hide_index=True)

    default_market_tickers = ["2330"] if "2330" in allowed_tickers else allowed_tickers[:1]
    selected_market_tickers = st.multiselect(
        "選擇要刷新或補文件的股票",
        options=allowed_tickers,
        default=default_market_tickers,
    )
    col_start, col_end = st.columns(2)
    with col_start:
        market_start = st.date_input(
            "起始日期", value=today_taipei().replace(day=1), key="market_start"
        )
    with col_end:
        market_end = st.date_input("結束日期", value=today_taipei(), key="market_end")

    has_market_selection = bool(selected_market_tickers)
    has_valid_market_range = market_start <= market_end
    if not has_market_selection:
        st.caption("請先選擇至少一檔股票。")
    if not has_valid_market_range:
        st.error("起始日期不可晚於結束日期。")

    refresh_cols = st.columns(4)
    refresh_price = refresh_cols[0].button(
        "刷新股價",
        type="primary",
        disabled=not (has_market_selection and has_valid_market_range),
    )
    refresh_financials = refresh_cols[1].button("刷新 5 年財報", disabled=not has_market_selection)
    refresh_valuations = refresh_cols[2].button(
        "刷新估值",
        disabled=not (has_market_selection and has_valid_market_range),
    )
    refresh_filings = refresh_cols[3].button("補抓公司文件", disabled=not has_market_selection)
    st.markdown(
        """
        <div class="action-impact-grid" aria-label="資料補強影響">
            <div><strong>刷新股價</strong><span>會更新最新版報告的股價與成交量判讀</span></div>
            <div><strong>刷新 5 年財報</strong><span>會補齊五年財務與品質門檻需要的財報資料</span></div>
            <div><strong>刷新估值</strong><span>會更新本益比、股價淨值比與殖利率判讀</span></div>
            <div><strong>補抓公司文件</strong><span>會補齊公司文件、法說會或公開資訊缺口</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    data_task_payload = {
        "tickers": selected_market_tickers,
        **task_payload_dates(market_start, market_end),
    }
    if refresh_price:
        submit_data_operation_task(
            "market_refresh",
            data_task_payload,
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出股價刷新背景任務",
            error_message="股價刷新任務送出失敗",
        )

    if refresh_financials:
        submit_data_operation_task(
            "fundamentals_refresh",
            {
                "tickers": selected_market_tickers,
                **task_payload_dates(market_end - timedelta(days=365 * 6), market_end),
            },
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出財報刷新背景任務",
            error_message="財報刷新任務送出失敗",
        )

    if refresh_valuations:
        submit_data_operation_task(
            "valuation_refresh",
            data_task_payload,
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出估值刷新背景任務",
            error_message="估值刷新任務送出失敗",
        )

    if refresh_filings:
        submit_data_operation_task(
            "company_filings_fetch",
            {"tickers": selected_market_tickers},
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出公司文件補抓背景任務",
            error_message="公司文件補抓任務送出失敗",
        )

    render_last_data_task_status(
        label="refresh_data_task_status",
        key="data_task_id_lookup",
        expanded=True,
    )
    _render_cache_summary(allowed_tickers)


def _render_cache_summary(allowed_tickers: list[str]) -> None:
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
