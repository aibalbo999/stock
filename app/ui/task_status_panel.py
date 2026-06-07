from __future__ import annotations

import requests
import streamlit as st

from app.ui.api_client import api_get, api_task_post, request_error_message


def render_task_status(task_status: dict) -> None:
    cols = st.columns(4)
    cols[0].metric("Task", task_status.get("status", "UNKNOWN"))
    cols[1].metric("Ready", str(task_status.get("ready", False)))
    cols[2].metric("Success", str(task_status.get("successful", False)))
    run = task_status.get("run")
    cols[3].metric("Run", f"#{run['id']}" if isinstance(run, dict) and run.get("id") else "-")
    progress = task_status.get("progress") if isinstance(task_status.get("progress"), dict) else {}
    progress_pct = progress.get("progress_pct")
    if isinstance(progress_pct, (int, float)):
        st.progress(max(0.0, min(float(progress_pct), 1.0)))
    if progress:
        st.caption(
            "進度："
            f"{progress.get('status') or task_status.get('status', 'UNKNOWN')}｜"
            f"{progress.get('current_step') or progress.get('next_incomplete_step') or '等待中'}"
        )
        if progress.get("resume_hint"):
            st.caption(str(progress["resume_hint"]))
    if task_status.get("result"):
        st.json(task_status["result"])
    if task_status.get("error"):
        st.error(task_status["error"])
    if isinstance(run, dict):
        st.dataframe(
            [
                {
                    "run_id": run.get("id"),
                    "status": run.get("status"),
                    "report_id": run.get("report_id"),
                    "output_path": run.get("output_path"),
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                }
            ],
            width="stretch",
            hide_index=True,
        )


def _task_status_ready(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("ready")) or str(task_status.get("status") or "").upper() in {
        "SUCCESS",
        "FAILURE",
        "REVOKED",
    }


def _fetch_task_status(task_id: str, status_state_key: str) -> dict | None:
    try:
        task_status = api_get(f"/tasks/{task_id}")
    except requests.RequestException as exc:
        st.error(f"查詢失敗：{request_error_message(exc)}")
        return None
    st.session_state[status_state_key] = task_status
    return task_status


def _render_task_status_panel_controls(
    *,
    task_id: str,
    refresh_key: str,
    status_state_key: str,
    apply_result_key: str | None,
) -> dict | None:
    task_status = st.session_state.get(status_state_key)
    if not isinstance(task_status, dict) or task_status.get("task_id") != task_id:
        return None
    render_task_status(task_status)
    action_cols = st.columns(2)
    with action_cols[0]:
        if st.button("取消任務", key=f"{refresh_key}_cancel"):
            try:
                st.session_state[status_state_key] = api_task_post(f"/tasks/{task_id}/cancel", {})
                st.success("已送出取消要求。")
            except requests.RequestException as exc:
                st.error(f"取消失敗：{request_error_message(exc)}")
    with action_cols[1]:
        if st.button("重試任務", key=f"{refresh_key}_retry"):
            try:
                retry_response = api_task_post(f"/tasks/{task_id}/retry", {})
                st.session_state["last_data_task_id"] = retry_response.get("task_id") or task_id
                st.session_state[status_state_key] = retry_response
                st.success(f"已送出重試任務：{retry_response.get('task_id')}")
            except requests.RequestException as exc:
                st.error(f"重試失敗：{request_error_message(exc)}")
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
    auto_refresh_seconds: int = 5,
) -> dict | None:
    if not task_id:
        st.warning("請輸入 task id。")
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
    if auto_refresh and not _task_status_ready(task_status) and callable(fragment_factory):
        interval = max(1, int(auto_refresh_seconds or 5))

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
            )

        return _auto_task_status_panel()
    if auto_refresh and not callable(fragment_factory):
        st.caption("目前 Streamlit 版本不支援片段式自動刷新；請使用手動刷新。")
    return _render_task_status_panel_controls(
        task_id=task_id,
        refresh_key=refresh_key,
        status_state_key=status_state_key,
        apply_result_key=apply_result_key,
    )
