from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.background_tasks import submit_data_operation_task
from app.ui.dashboard_core import render_section_header
from app.ui.data_enrichment_common import (
    DATA_TASK_STATUS_STATE_KEYS,
    render_data_ingest_submission_summary,
    render_last_data_task_status,
)


def render_rss_ingest_tab() -> None:
    render_section_header("RSS 匯入", "從既有資料源或指定 URL 抓取最新文本。")
    configured_sources = load_api_json_or_default(
        "/news/sources",
        [],
        error_message="讀取 RSS 來源失敗",
    )
    if configured_sources:
        st.dataframe(
            configured_sources,
            width="stretch",
            hide_index=True,
        )
    feed_url = st.text_input("RSS URL")
    feed_publisher = st.text_input("來源名稱", value="rss")
    feed_limit = st.number_input("抓取筆數", min_value=1, max_value=50, value=10)
    feed_ready = bool(feed_url.strip())
    if not feed_ready:
        st.caption("請先輸入 RSS URL。")
    rss_fetch_confirmed = st.checkbox(
        "我了解這會送出 RSS 抓取背景任務",
        value=False,
        key="confirm_rss_fetch_submission",
    )
    if feed_ready and not rss_fetch_confirmed:
        st.caption("避免誤觸 RSS 抓取；確認 URL、來源與筆數後才會送出背景任務。")
    render_data_ingest_submission_summary(
        rss_fetch_preflight_summary(
            feed_url=feed_url,
            publisher=feed_publisher,
            limit=int(feed_limit),
            ready=feed_ready,
            confirmed=rss_fetch_confirmed,
        ),
        streamlit_module=st,
    )
    if st.button(
        "抓取 RSS",
        type="primary",
        disabled=not feed_ready or not rss_fetch_confirmed,
    ):
        submit_data_operation_task(
            "feed_fetch",
            {
                "url": feed_url.strip(),
                "publisher": (feed_publisher or "rss").strip(),
                "limit": int(feed_limit),
            },
            status_state_keys=DATA_TASK_STATUS_STATE_KEYS,
            success_message="已送出 RSS 抓取背景任務",
            error_message="RSS 抓取任務送出失敗",
        )

    render_last_data_task_status(
        label="refresh_rss_data_task_status",
        key="rss_data_task_id_lookup",
    )


def rss_fetch_preflight_summary(
    *,
    feed_url: str,
    publisher: str,
    limit: int,
    ready: bool,
    confirmed: bool,
) -> dict[str, str]:
    detail = (
        f"來源：{_text(publisher, default='rss')}｜"
        f"筆數：{int(limit)}｜URL：{_text(feed_url, default='尚未填寫')}"
    )
    if not ready:
        return {
            "state": "attention",
            "title": "RSS 抓取尚未完整",
            "detail": detail,
            "next_step": "請先輸入 RSS URL。",
            "quota_hint": "尚未送出背景任務；確認 URL 可避免失敗重試浪費排隊資源。",
        }
    if not confirmed:
        return {
            "state": "attention",
            "title": "準備送出 RSS 抓取",
            "detail": detail,
            "next_step": "勾選確認後，再按「抓取 RSS」送出背景任務。",
            "quota_hint": "背景任務會排隊抓取與匯入文本；完成前不要重複送出同一個 RSS。",
        }
    return {
        "state": "ready",
        "title": "可以送出 RSS 抓取",
        "detail": detail,
        "next_step": "按「抓取 RSS」送出背景任務；完成後回報告中心確認最新版。",
        "quota_hint": "背景任務會排隊抓取與匯入文本；完成前不要重複送出同一個 RSS。",
    }


def _text(value: object, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
