from __future__ import annotations

import json

import streamlit as st

from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_delete
from app.ui.api_loaders import load_api_json_or_default
from app.ui.dashboard_core import render_section_header
from app.ui.report_center_presenter import (
    report_run_detail_error_message,
    report_run_history_ids,
    report_run_history_rows,
)
from app.ui.report_state import parse_json_object
from app.ui.task_status_panel import render_task_status_panel


def render_report_history_debug_panel(
    *,
    selected_id: int | None,
    report_title: str,
) -> None:
    with st.expander("疑難排解：執行紀錄"):
        render_section_header(
            "執行紀錄", "一般閱讀報告不需要查看；舊版報告與背景任務只在這裡查錯或追蹤。"
        )
        if selected_id is not None:
            _render_report_management_controls(selected_id, report_title)
            st.divider()
        _render_run_history_controls()


def _render_report_management_controls(selected_id: int, report_title: str) -> None:
    st.markdown("#### 報告管理")
    st.caption("進階操作，只在需要移除最新版報告時使用。")
    st.caption("刪除報告會移除目前最新版報告與安全範圍內的報告檔；分析紀錄會保留。")
    report_delete_confirmed = st.checkbox(
        f"我了解會刪除目前選取的報告 #{selected_id}",
        value=False,
        key=f"confirm_delete_report_{selected_id}",
    )
    if not report_delete_confirmed:
        st.caption("勾選確認後才會啟用刪除此報告，避免誤觸。")
    if st.button(
        "刪除此報告",
        key=f"delete_report_{selected_id}",
        disabled=not report_delete_confirmed,
    ):
        deleted = run_api_action_or_none(
            lambda: api_delete(f"/reports/{int(selected_id)}"),
            error_message="刪除失敗",
        )
        if isinstance(deleted, dict):
            st.success(f"已刪除報告 #{selected_id}｜{report_title}")
            st.rerun()


def _render_run_history_controls() -> None:
    runs = load_api_json_or_default(
        "/runs?limit=20",
        [],
        error_message="讀取執行紀錄失敗",
    )
    run_rows = report_run_history_rows(runs)
    run_ids = report_run_history_ids(runs)
    if not run_rows:
        st.info("尚無任務執行紀錄。")
        return

    st.dataframe(
        run_rows,
        width="stretch",
        hide_index=True,
    )
    selected_run_id = st.selectbox(
        "查看執行紀錄",
        options=run_ids,
        format_func=lambda run_id: f"紀錄 #{run_id}",
    )
    selected_run = load_api_json_or_default(
        f"/runs/{int(selected_run_id)}",
        {},
        error_message="讀取紀錄失敗",
    )
    if isinstance(selected_run, dict):
        selected_run_payload = selected_run.get("payload") or "{}"
        selected_run_error = selected_run.get("error")
    else:
        selected_run_payload = "{}"
        selected_run_error = None
    selected_payload = parse_json_object(selected_run_payload)
    selected_task_id = selected_payload.get("celery_task_id")
    with st.expander("原始紀錄內容"):
        try:
            st.json(json.loads(selected_run_payload))
        except json.JSONDecodeError:
            st.code(selected_run_payload)
    if selected_task_id:
        with st.expander("背景任務狀態", expanded=False):
            render_task_status_panel(
                task_id=str(selected_task_id),
                refresh_key=f"history_run_task_status_{selected_run_id}",
            )
    if selected_run_error:
        st.error(report_run_detail_error_message(selected_run_error))
    run_delete_confirmed = st.checkbox(
        f"我了解會刪除分析紀錄 #{selected_run_id}",
        value=False,
        key=f"confirm_delete_run_{selected_run_id}",
    )
    st.caption("刪除分析紀錄只會移除此筆執行歷史，不會刪除目前最新版報告。")
    if not run_delete_confirmed:
        st.caption("勾選確認後才會啟用刪除此分析紀錄，避免誤觸。")
    if st.button(
        "刪除此分析紀錄",
        key=f"delete_run_{selected_run_id}",
        disabled=not run_delete_confirmed,
    ):
        deleted = run_api_action_or_none(
            lambda: api_delete(f"/runs/{int(selected_run_id)}"),
            error_message="刪除失敗",
        )
        if isinstance(deleted, dict):
            st.success(f"已刪除分析紀錄 #{selected_run_id}")
            st.rerun()
