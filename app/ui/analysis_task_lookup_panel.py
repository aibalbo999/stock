from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.task_status_panel import render_task_status_panel


def render_analysis_task_lookup_panel() -> None:
    with st.expander("疑難排解：查詢背景分析"):
        last_task_id = st.session_state.get("last_async_task_id")
        task_id = st.text_input("背景分析編號", value=last_task_id or "")
        render_task_status_panel(
            task_id=task_id,
            refresh_key="refresh_analysis_task_status",
            apply_result_key="apply_analysis_task_result",
            task_state_key="last_async_task_id",
        )
        if st.button("查詢紀錄", key="lookup_analysis_task_run"):
            if not task_id:
                st.warning("請輸入任務編號。")
                return
            task_run = load_api_json_or_default(
                f"/tasks/{task_id}/run",
                None,
                error_message="查詢失敗",
                not_found_message="尚未找到對應紀錄；任務剛送出時可能需要等待。",
            )
            if task_run is not None:
                st.json(task_run)
