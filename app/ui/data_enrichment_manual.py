from __future__ import annotations

from typing import Any

import streamlit as st

from app.core.time import today_taipei
from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_post
from app.ui.background_tasks import submit_data_operation_task
from app.ui.dashboard_core import render_section_header
from app.ui.data_enrichment_common import (
    DATA_TASK_STATUS_STATE_KEYS,
    render_last_data_task_status,
)


def render_manual_ingest_tab(whitelist: Any, allowed_tickers: list[str]) -> None:
    render_section_header("手動補充", "補充新聞、法說或研究摘要，讓報告可以引用具體來源。")
    _render_pending_manual_ingest_notice()
    input_tabs = st.tabs(["新聞/研究摘要", "公司公開文件"])
    with input_tabs[0]:
        _render_manual_news_form()
    with input_tabs[1]:
        _render_company_filing_form(whitelist, allowed_tickers)

    render_last_data_task_status(
        label="refresh_manual_data_task_status",
        key="manual_data_task_id_lookup",
    )


def _render_manual_news_form() -> None:
    title = st.text_input("標題")
    publisher = st.text_input("來源", value="manual")
    published_at = st.date_input("日期", value=today_taipei())
    url = st.text_input("URL")
    text = st.text_area("內文", height=260)
    manual_news_ready = bool(title.strip() and text.strip())
    if not manual_news_ready:
        st.caption("請先填入標題與內文。")
    if st.button("匯入新聞/研究摘要", type="primary", disabled=not manual_news_ready):
        result = run_api_action_or_none(
            lambda: api_post(
                "/ingest/manual",
                {
                    "title": title.strip(),
                    "text": text.strip(),
                    "publisher": (publisher or "manual").strip(),
                    "published_at": published_at.isoformat(),
                    "url": url.strip() or None,
                },
            ),
            error_message="匯入失敗",
        )
        if isinstance(result, dict):
            st.success(f"已匯入：{result.get('document_id')}")


def _render_company_filing_form(whitelist: Any, allowed_tickers: list[str]) -> None:
    if not allowed_tickers:
        st.warning("目前沒有可選股票代號。")
        return
    filing_ticker = st.selectbox(
        "股票代號",
        options=allowed_tickers,
        index=allowed_tickers.index("2330") if "2330" in allowed_tickers else 0,
    )
    filing_company = st.text_input(
        "公司名稱",
        value=next(
            (company.name for company in whitelist.companies() if company.ticker == filing_ticker),
            "",
        ),
    )
    filing_type = st.selectbox(
        "文件類型",
        options=[
            "annual_report",
            "investor_presentation",
            "prospectus",
            "material_information",
            "company_disclosure",
        ],
        format_func=lambda value: {
            "annual_report": "年報",
            "investor_presentation": "法說/投資人簡報",
            "prospectus": "公開說明書",
            "material_information": "重大訊息",
            "company_disclosure": "其他公司揭露",
        }.get(value, value),
    )
    filing_title = st.text_input("文件標題", key="filing_title")
    filing_publisher = st.text_input("文件來源", value="公司 IR / MOPS", key="filing_publisher")
    filing_date = st.date_input("文件日期", value=today_taipei(), key="filing_date")
    filing_url = st.text_input("文件 URL", key="filing_url")
    filing_text = st.text_area("文件文字", height=260, key="filing_text")
    filing_text_ready = bool(filing_title.strip() and filing_text.strip())
    filing_url_ready = bool(filing_url.strip())
    if not filing_text_ready and not filing_url_ready:
        st.caption("貼上文件文字時需有標題；或提供文件 URL 後從 URL 匯入。")
    filing_import_cols = st.columns(2)
    import_text_filing = filing_import_cols[0].button(
        "匯入公司文件",
        type="primary",
        disabled=not filing_text_ready,
    )
    import_url_filing = filing_import_cols[1].button(
        "從 URL 抓取並匯入",
        disabled=not filing_url_ready,
    )
    if import_text_filing:
        _submit_manual_company_filing(
            filing_ticker=filing_ticker,
            filing_company=filing_company,
            filing_type=filing_type,
            filing_title=filing_title,
            filing_text=filing_text,
            filing_publisher=filing_publisher,
            filing_date=filing_date,
            filing_url=filing_url,
        )
    if import_url_filing:
        submit_data_operation_task(
            "company_filing_from_url",
            {
                "url": filing_url.strip(),
                "ticker": filing_ticker,
                "company_name": filing_company,
                "document_type": filing_type,
                "publisher": (filing_publisher or "公司 IR / MOPS").strip(),
                "published_at": filing_date.isoformat(),
            },
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出 URL 公司文件匯入背景任務",
            error_message="URL 公司文件匯入任務送出失敗",
        )


def _render_pending_manual_ingest_notice() -> None:
    pending_operation = st.session_state.get("pending_data_enrichment_operation")
    if pending_operation != "manual_ingest":
        return
    st.session_state.pop("pending_data_enrichment_operation", None)
    pending_tickers = st.session_state.pop("pending_data_enrichment_tickers", None)
    tickers = (
        [str(ticker).strip() for ticker in pending_tickers if str(ticker).strip()]
        if isinstance(pending_tickers, list)
        else []
    )
    ticker_label = "、".join(tickers) if tickers else "最新版報告相關股票"
    st.info(f"已依資料缺口準備匯入新聞/研究摘要，股票：{ticker_label}。請貼上標題與內文後送出。")


def _submit_manual_company_filing(
    *,
    filing_ticker: str,
    filing_company: str,
    filing_type: str,
    filing_title: str,
    filing_text: str,
    filing_publisher: str,
    filing_date: Any,
    filing_url: str,
) -> None:
    result = run_api_action_or_none(
        lambda: api_post(
            "/company-filings/manual",
            {
                "ticker": filing_ticker,
                "company_name": filing_company,
                "document_type": filing_type,
                "title": filing_title.strip(),
                "text": filing_text.strip(),
                "publisher": (filing_publisher or "公司 IR / MOPS").strip(),
                "published_at": filing_date.isoformat(),
                "url": filing_url.strip() or None,
            },
        ),
        error_message="匯入公司文件失敗",
    )
    if isinstance(result, dict):
        st.success(f"已匯入公司文件：{result.get('document_id')}")
        st.caption(
            f"來源分級：{result.get('source_tier')}；品質分數：{result.get('quality_score')}"
        )
