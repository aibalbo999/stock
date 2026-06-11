from __future__ import annotations

import streamlit as st

from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_task_post
from app.ui.api_loaders import load_api_json_or_default
from app.ui.task_status_presenter import (
    task_action_preflight_summary,
    task_status_poll_caption,
    task_status_poll_interval_seconds,
)
from app.ui.task_status_view import (
    company_filing_gap_rows,
    task_action_preflight_summary_html,
    task_execution_context_rows,
    task_run_summary_rows,
    task_status_diagnostic_rows,
    task_status_metric_values,
    task_status_progress_caption,
)


def render_task_action_preflight_summary(summary: dict[str, str]) -> None:
    if not summary:
        return
    st.markdown(
        task_action_preflight_summary_html(summary),
        unsafe_allow_html=True,
    )


def render_task_status(task_status: dict) -> None:
    cols = st.columns(4)
    for column, metric in zip(cols, task_status_metric_values(task_status), strict=False):
        column.metric(metric["label"], metric["value"])
    progress = task_status.get("progress") if isinstance(task_status.get("progress"), dict) else {}
    progress_pct = progress.get("progress_pct")
    if isinstance(progress_pct, (int, float)):
        st.progress(max(0.0, min(float(progress_pct), 1.0)))
    progress_caption = task_status_progress_caption(task_status)
    if progress_caption:
        st.caption(progress_caption)
        if progress.get("resume_hint"):
            st.caption(str(progress["resume_hint"]))
    company_filing_rows = company_filing_gap_rows(task_status)
    if company_filing_rows:
        st.caption("公司文件補抓摘要")
        st.dataframe(company_filing_rows, width="stretch", hide_index=True)
    execution_rows = task_execution_context_rows(task_status)
    if execution_rows:
        st.caption("執行上下文")
        st.dataframe(execution_rows, width="stretch", hide_index=True)
    if task_status.get("result"):
        st.json(task_status["result"])
    if task_status.get("error"):
        st.error(task_status["error"])
    diagnostic_rows = task_status_diagnostic_rows(task_status)
    if diagnostic_rows:
        st.caption("失敗診斷")
        st.dataframe(diagnostic_rows, width="stretch", hide_index=True)
    run_summary_rows = task_run_summary_rows(task_status)
    if run_summary_rows:
        st.dataframe(run_summary_rows, width="stretch", hide_index=True)


def _task_status_ready(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("ready")) or str(task_status.get("status") or "").upper() in {
        "SUCCESS",
        "FAILURE",
        "REVOKED",
    }


def _task_status_successful(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("successful")) or str(task_status.get("status") or "").upper() == (
        "SUCCESS"
    )


def _fetch_task_status(task_id: str, status_state_key: str) -> dict | None:
    task_status = load_api_json_or_default(
        f"/tasks/{task_id}",
        None,
        error_message="查詢失敗",
    )
    if not isinstance(task_status, dict):
        return None
    st.session_state[status_state_key] = task_status
    return task_status


def _render_task_status_panel_controls(
    *,
    task_id: str,
    refresh_key: str,
    status_state_key: str,
    apply_result_key: str | None,
    task_state_key: str | None,
) -> dict | None:
    task_status = st.session_state.get(status_state_key)
    if not isinstance(task_status, dict) or task_status.get("task_id") != task_id:
        return None
    render_task_status(task_status)
    action_cols = st.columns(2)
    with action_cols[0]:
        cancel_confirmed = st.checkbox(
            "我了解這會取消目前背景任務",
            value=False,
            key=f"{refresh_key}_confirm_cancel",
        )
        if not cancel_confirmed:
            st.caption("避免誤觸取消；確認後才可送出取消要求。")
        cancel_summary = task_action_preflight_summary(
            task_status,
            action="cancel",
            confirmed=cancel_confirmed,
        )
        render_task_action_preflight_summary(cancel_summary)
        cancel_blocked = cancel_summary.get("state") == "blocked"
        if st.button(
            "取消任務",
            key=f"{refresh_key}_cancel",
            disabled=cancel_blocked or not cancel_confirmed,
        ):
            cancel_response = run_api_action_or_none(
                lambda: api_task_post(f"/tasks/{task_id}/cancel", {}),
                error_message="取消失敗",
            )
            if isinstance(cancel_response, dict):
                st.session_state[status_state_key] = cancel_response
                st.success("已送出取消要求。")
    with action_cols[1]:
        retry_confirmed = st.checkbox(
            "我了解這會重新送出任務，可能消耗模型或資料源額度",
            value=False,
            key=f"{refresh_key}_confirm_retry",
        )
        if not retry_confirmed:
            st.caption("避免誤觸重試；確認後才可重新送出並消耗額度。")
        retry_summary = task_action_preflight_summary(
            task_status,
            action="retry",
            confirmed=retry_confirmed,
        )
        render_task_action_preflight_summary(retry_summary)
        retry_blocked = retry_summary.get("state") == "blocked"
        if st.button(
            "重試任務",
            key=f"{refresh_key}_retry",
            disabled=retry_blocked or not retry_confirmed,
        ):
            retry_response = run_api_action_or_none(
                lambda: api_task_post(f"/tasks/{task_id}/retry", {}),
                error_message="重試失敗",
            )
            if isinstance(retry_response, dict):
                retry_task_id = retry_response.get("task_id") or task_id
                if task_state_key:
                    st.session_state[task_state_key] = retry_task_id
                st.session_state[status_state_key] = retry_response
                st.success(f"已送出重試任務：{retry_task_id}")
    result = (task_status or {}).get("result")
    if (
        apply_result_key
        and isinstance(result, dict)
        and isinstance(result.get("report"), dict)
        and st.button("載入本次分析結果", key=apply_result_key)
    ):
        st.session_state["last_analysis_result"] = result
        active_report_id = result.get("active_report_id") or result.get("report_id")
        if active_report_id:
            st.session_state["pending_selected_report_id"] = int(active_report_id)
        st.rerun()
    return task_status


def render_task_status_panel(
    *,
    task_id: str,
    refresh_key: str,
    apply_result_key: str | None = None,
    task_state_key: str | None = None,
    auto_refresh_seconds: int = 5,
) -> dict | None:
    if not task_id:
        st.warning("請輸入任務編號。")
        return None
    status_state_key = f"{refresh_key}_status"
    task_status = st.session_state.get(status_state_key)
    if isinstance(task_status, dict) and task_status.get("task_id") != task_id:
        task_status = None
        st.session_state.pop(status_state_key, None)
    control_cols = st.columns([1, 1])
    with control_cols[0]:
        if st.button("刷新狀態", key=refresh_key):
            task_status = _fetch_task_status(task_id, status_state_key)
            if task_status is None:
                return None
    with control_cols[1]:
        auto_refresh = st.toggle(
            "自動刷新",
            value=not _task_status_ready(task_status),
            key=f"{refresh_key}_auto_refresh",
        )
    if not isinstance(task_status, dict):
        task_status = _fetch_task_status(task_id, status_state_key)
    fragment_factory = getattr(st, "fragment", None)
    fragment_supported = callable(fragment_factory)
    st.caption(
        task_status_poll_caption(
            task_status,
            auto_refresh=auto_refresh,
            fragment_supported=fragment_supported,
            default_seconds=auto_refresh_seconds,
        )
    )
    if auto_refresh and not _task_status_ready(task_status) and fragment_supported:
        interval = task_status_poll_interval_seconds(
            task_status,
            default_seconds=auto_refresh_seconds,
        )

        @fragment_factory(run_every=f"{interval}s")
        def _auto_task_status_panel() -> dict | None:
            current_status = st.session_state.get(status_state_key)
            if not _task_status_ready(current_status if isinstance(current_status, dict) else None):
                _fetch_task_status(task_id, status_state_key)
            return _render_task_status_panel_controls(
                task_id=task_id,
                refresh_key=refresh_key,
                status_state_key=status_state_key,
                apply_result_key=apply_result_key,
                task_state_key=task_state_key,
            )

        return _auto_task_status_panel()
    return _render_task_status_panel_controls(
        task_id=task_id,
        refresh_key=refresh_key,
        status_state_key=status_state_key,
        apply_result_key=apply_result_key,
        task_state_key=task_state_key,
    )
