from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.follow_up_status import follow_up_result_message
from app.ui.task_status_panel import render_task_status_panel


def render_follow_up_task_status_panel(
    key_suffix: str,
    *,
    streamlit_module: Any = st,
) -> None:
    last_follow_up_task_id = streamlit_module.session_state.get("last_follow_up_task_id")
    if not last_follow_up_task_id:
        return
    with streamlit_module.expander("背景補強任務狀態", expanded=True):
        task_id = streamlit_module.text_input(
            "補強任務編號",
            value=last_follow_up_task_id,
            key=f"followup_task_lookup_{key_suffix}",
        )
        task_status = render_task_status_panel(
            task_id=task_id,
            refresh_key=f"refresh_followup_task_{key_suffix}",
            task_state_key="last_follow_up_task_id",
        )
        result = (task_status or {}).get("result") if isinstance(task_status, dict) else None
        if isinstance(result, dict) and streamlit_module.button(
            "套用背景補強結果", key=f"apply_followup_task_{key_suffix}"
        ):
            streamlit_module.session_state["last_follow_up_result"] = result
            selected_summary = (result.get("summary") or {}).get("selected") or {}
            execution_summary = (result.get("summary") or {}).get("execution") or {}
            summary_text = (
                f"執行 {selected_summary.get('total_count', len(result.get('actions') or []))} 項任務"
                f"（資料缺口 {selected_summary.get('required_count', 0)}、"
                f"追蹤更新 {selected_summary.get('tracking_count', 0)}）"
            )
            if execution_summary:
                summary_text += (
                    f"，補入/更新 {execution_summary.get('stored_count', 0)} 筆資料"
                    f"，錯誤 {execution_summary.get('error_count', 0)} 項"
                )
            message_level, message_text = follow_up_result_message(result, summary_text)
            streamlit_module.session_state["follow_up_flash"] = {
                "level": message_level,
                "message": message_text,
                "result": result,
            }
            new_report = result.get("rerun_report") or {}
            if new_report.get("report_id"):
                streamlit_module.session_state["pending_selected_report_id"] = int(
                    new_report["report_id"]
                )
            streamlit_module.rerun()
