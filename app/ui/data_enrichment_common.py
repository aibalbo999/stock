from __future__ import annotations

import streamlit as st

from app.ui.task_status_panel import render_task_status_panel


DATA_TASK_STATUS_STATE_KEYS = (
    "refresh_data_task_status_status",
    "refresh_manual_data_task_status_status",
    "refresh_rss_data_task_status_status",
)


def render_last_data_task_status(*, label: str, key: str, expanded: bool = False) -> None:
    last_data_task_id = st.session_state.get("last_data_task_id")
    if not last_data_task_id:
        return
    with st.expander("背景資料任務狀態", expanded=expanded):
        data_task_id = st.text_input("資料任務編號", value=last_data_task_id, key=key)
        render_task_status_panel(
            task_id=data_task_id,
            refresh_key=label,
            task_state_key="last_data_task_id",
        )
