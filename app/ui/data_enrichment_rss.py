from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.background_tasks import submit_data_operation_task
from app.ui.dashboard_core import render_section_header
from app.ui.data_enrichment_common import (
    DATA_TASK_STATUS_STATE_KEYS,
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
