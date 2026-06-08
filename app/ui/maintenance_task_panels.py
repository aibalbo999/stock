from __future__ import annotations

import streamlit as st

from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_post, api_task_post
from app.ui.task_failure_diagnostics import (
    task_failure_action_route_rows,
    task_failure_drilldown_rows,
    task_retry_options,
)
from app.ui.task_queue_diagnostics import (
    task_queue_health_alert,
    task_queue_health_rows,
    task_queue_repair_rows,
    task_queue_smoke_command,
)
from app.ui.task_status_panel import render_task_status_panel


def render_background_task_observability_panel(
    service_snapshot: dict,
    task_summary: dict,
    maintenance_diagnostics: dict | None = None,
) -> None:
    with st.expander("背景任務觀測", expanded=False):
        st.caption("Queue / Worker readiness")
        st.dataframe(task_queue_health_rows(service_snapshot), width="stretch", hide_index=True)
        repair_rows = task_queue_repair_rows(service_snapshot)
        if repair_rows:
            st.caption("Queue 修復指引")
            st.dataframe(repair_rows, width="stretch", hide_index=True)
        queue_alert = task_queue_health_alert(service_snapshot)
        if queue_alert:
            message = str(queue_alert.get("message") or "")
            if queue_alert.get("severity") == "error":
                st.error(message)
            elif queue_alert.get("severity") == "warning":
                st.warning(message)
            elif queue_alert.get("severity") == "success":
                st.success(message)
            else:
                st.info(message)
        smoke_command = task_queue_smoke_command(service_snapshot)
        if smoke_command:
            st.caption("診斷指令")
            st.code(smoke_command, language="bash")
        _render_maintenance_diagnostic_actions(maintenance_diagnostics or {})
        _render_task_summary_alerts(task_summary)
        _render_task_summary_metrics(task_summary)
        _render_task_failure_drilldown(task_summary)


def _render_task_summary_alerts(task_summary: dict) -> None:
    task_alerts = [alert for alert in task_summary.get("alerts") or [] if isinstance(alert, dict)]
    for alert in task_alerts:
        message = str(alert.get("message") or alert.get("code") or "")
        next_steps = [str(step) for step in alert.get("next_steps") or [] if str(step).strip()]
        if next_steps:
            message = f"{message} 建議：" + "；".join(next_steps)
        if alert.get("severity") == "error":
            st.error(message)
        elif alert.get("severity") == "warning":
            st.warning(message)
        else:
            st.info(message)


def _render_task_summary_metrics(task_summary: dict) -> None:
    task_totals = task_summary.get("totals") if isinstance(task_summary.get("totals"), dict) else {}
    task_cols = st.columns(5)
    task_cols[0].metric("7 日任務", int(task_totals.get("run_count") or 0))
    task_cols[1].metric(
        "成功率",
        "-"
        if task_totals.get("success_rate") is None
        else f"{float(task_totals['success_rate']) * 100:.1f}%",
    )
    task_cols[2].metric("失敗", int(task_totals.get("failed_count") or 0))
    task_cols[3].metric("執行中", int(task_totals.get("running_count") or 0))
    task_cols[4].metric("疑似卡住", int(task_totals.get("stale_running_count") or 0))
    if task_summary.get("by_operation"):
        st.caption("任務類型")
        st.dataframe(task_summary["by_operation"], width="stretch", hide_index=True)
    if task_summary.get("by_error_category"):
        st.caption("失敗原因分類")
        st.dataframe(task_summary["by_error_category"], width="stretch", hide_index=True)
    if task_summary.get("error_category_daily"):
        st.caption("失敗原因趨勢")
        st.dataframe(task_summary["error_category_daily"], width="stretch", hide_index=True)


def _render_task_failure_drilldown(task_summary: dict) -> None:
    failure_rows = task_failure_drilldown_rows(task_summary)
    if failure_rows:
        st.caption("近期失敗 / 取消")
        action_route_rows = task_failure_action_route_rows(task_summary)
        if action_route_rows:
            st.caption("失敗處理路徑")
            st.dataframe(action_route_rows, width="stretch", hide_index=True)
        st.dataframe(failure_rows, width="stretch", hide_index=True)
        retry_options = task_retry_options(task_summary)
        if retry_options:
            _render_task_retry_controls(retry_options)
        else:
            st.caption("目前近期失敗沒有可由 API 自動重試的 task payload。")
    inspect_task_id = st.session_state.get("maintenance_inspect_task_id")
    if inspect_task_id:
        st.caption("任務狀態 drilldown")
        render_task_status_panel(
            task_id=str(inspect_task_id),
            refresh_key="maintenance_retry_task_status",
            task_state_key="maintenance_inspect_task_id",
        )


def _render_task_retry_controls(retry_options: list[dict]) -> None:
    retry_options_by_id = {str(option["task_id"]): option for option in retry_options}
    retry_labels = {task_id: option["label"] for task_id, option in retry_options_by_id.items()}
    selected_retry_task_id = st.selectbox(
        "選擇要重試的失敗任務",
        options=[option["task_id"] for option in retry_options],
        format_func=lambda task_id: retry_labels.get(str(task_id), str(task_id)),
        key="maintenance_retry_task_select",
    )
    selected_retry_option = retry_options_by_id.get(str(selected_retry_task_id), {})
    selected_retry_guarded = bool(selected_retry_option.get("retry_guarded"))
    selected_retry_guard_message = str(selected_retry_option.get("retry_guard_message") or "")
    if selected_retry_guarded and selected_retry_guard_message:
        st.warning(selected_retry_guard_message)
    retry_cols = st.columns([1, 1])
    with retry_cols[0]:
        if st.button(
            "重試選取任務",
            key="maintenance_retry_failed_task",
            disabled=selected_retry_guarded,
        ):
            retry_response = run_api_action_or_none(
                lambda: api_task_post(
                    f"/tasks/{selected_retry_task_id}/retry",
                    {},
                ),
                error_message="重試失敗",
            )
            if isinstance(retry_response, dict):
                retry_task_id = str(retry_response.get("task_id") or selected_retry_task_id)
                st.session_state["maintenance_inspect_task_id"] = retry_task_id
                st.success(f"已送出重試任務：{retry_task_id}")
    with retry_cols[1]:
        if st.button("查看選取任務", key="maintenance_inspect_failed_task"):
            st.session_state["maintenance_inspect_task_id"] = selected_retry_task_id


def maintenance_diagnostic_action_rows(maintenance_diagnostics: dict) -> list[dict]:
    actions = (
        maintenance_diagnostics.get("actions")
        if isinstance(maintenance_diagnostics.get("actions"), list)
        else []
    )
    return [
        {
            "動作": action.get("label") or action.get("id") or "-",
            "狀態": "可執行" if action.get("read_only") else "停用",
            "說明": action.get("description") or "-",
            "指令": action.get("display_command") or "-",
            "Timeout": int(action.get("timeout_seconds") or 0),
        }
        for action in actions
        if isinstance(action, dict)
    ]


def _render_maintenance_diagnostic_actions(maintenance_diagnostics: dict) -> None:
    action_rows = maintenance_diagnostic_action_rows(maintenance_diagnostics)
    actions = [
        action
        for action in maintenance_diagnostics.get("actions") or []
        if isinstance(action, dict) and action.get("id") and action.get("read_only")
    ]
    if not action_rows or not actions:
        return
    st.caption("維護診斷動作")
    st.dataframe(action_rows, width="stretch", hide_index=True)
    action_by_id = {str(action["id"]): action for action in actions}
    selected_action_id = st.selectbox(
        "選擇診斷動作",
        options=list(action_by_id),
        format_func=lambda action_id: str(action_by_id[action_id].get("label") or action_id),
        key="maintenance_diagnostic_action_select",
    )
    if st.button("執行診斷", key="maintenance_run_diagnostic_action"):
        result = run_api_action_or_none(
            lambda: api_post(
                f"/maintenance/diagnostics/{selected_action_id}/run",
                {},
                timeout=120,
            ),
            error_message="診斷執行失敗",
        )
        if isinstance(result, dict):
            _render_maintenance_diagnostic_result(result)


def _render_maintenance_diagnostic_result(result: dict) -> None:
    status = str(result.get("status") or "")
    message = str(result.get("message") or status or "診斷完成")
    if status == "success":
        st.success(message)
    elif status in {"failed", "timeout"}:
        st.warning(message)
    else:
        st.info(message)
    output = "\n".join(
        part
        for part in (
            str(result.get("stdout_tail") or "").strip(),
            str(result.get("stderr_tail") or "").strip(),
        )
        if part
    )
    if output:
        st.code(output, language="text")
