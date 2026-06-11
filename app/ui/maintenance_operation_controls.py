from __future__ import annotations

import streamlit as st

from app.ui.background_tasks import submit_api_task
from app.ui.maintenance_deployment_presenter import (
    maintenance_operation_post_run_check_rows,
    maintenance_operation_post_run_diagnostic_action_rows,
    maintenance_operation_recommendation_caption,
    maintenance_operation_rows,
)
from app.ui.task_status_panel import render_task_status_panel

LAST_MAINTENANCE_OPERATION_TASK_KEY = "last_maintenance_operation_task_id"
LAST_POST_RUN_DIAGNOSTIC_TASK_KEY = "last_post_run_diagnostic_task_id"


def render_maintenance_operations(
    maintenance_operations: dict,
    *,
    recommended_operation_id: str = "",
) -> None:
    operation_rows = maintenance_operation_rows(maintenance_operations)
    operations = [
        operation
        for operation in maintenance_operations.get("operations") or []
        if isinstance(operation, dict)
        and operation.get("id")
        and operation.get("mutates_local_state")
    ]
    if not operation_rows or not operations:
        return
    st.caption("本機依賴操作")
    st.dataframe(operation_rows, width="stretch", hide_index=True)
    operation_by_id = {str(operation["id"]): operation for operation in operations}
    recommendation = maintenance_operation_recommendation_caption(
        maintenance_operations,
        recommended_operation_id,
    )
    if recommendation:
        st.caption(recommendation)
    operation_options = list(operation_by_id)
    recommended_operation_index = (
        operation_options.index(recommended_operation_id)
        if recommended_operation_id in operation_by_id
        else 0
    )
    selected_operation_id = st.selectbox(
        "選擇維護操作",
        options=operation_options,
        index=recommended_operation_index,
        format_func=lambda operation_id: str(
            operation_by_id[operation_id].get("label") or operation_id
        ),
        key="maintenance_operation_select",
    )
    operation_confirmed = st.checkbox(
        "我了解此操作會啟動本機 Docker 依賴，且只套用目前 API 程序的環境預設。",
        key="confirm_maintenance_operation",
    )
    if st.button(
        "執行維護操作",
        key="maintenance_run_operation",
        disabled=not operation_confirmed,
    ):
        submit_api_task(
            f"/tasks/maintenance-operation/{selected_operation_id}",
            {"confirmed": True},
            task_state_key=LAST_MAINTENANCE_OPERATION_TASK_KEY,
            status_state_keys=("refresh_maintenance_operation_task_status_status",),
            success_message="已送出維護操作背景任務",
            error_message="維護操作執行失敗",
            task_type_state_key="last_maintenance_operation_type",
            task_type=str(selected_operation_id),
        )
    last_task_id = st.session_state.get(LAST_MAINTENANCE_OPERATION_TASK_KEY)
    if last_task_id:
        with st.expander("維護操作背景任務狀態", expanded=True):
            task_status = render_task_status_panel(
                task_id=str(last_task_id),
                refresh_key="refresh_maintenance_operation_task_status",
                task_state_key=LAST_MAINTENANCE_OPERATION_TASK_KEY,
            )
            result = task_result_payload(task_status)
            if result:
                render_maintenance_operation_result(result)


def render_maintenance_operation_result(result: dict) -> None:
    status = str(result.get("status") or "")
    message = str(result.get("message") or status or "維護操作完成")
    if status == "success":
        st.success(message)
    elif status in {"partial", "needs_download", "skipped"}:
        st.warning(message)
    elif status == "failed":
        st.error(message)
    else:
        st.info(message)
    wait_lines = [str(line) for line in result.get("wait_lines") or [] if str(line).strip()]
    if wait_lines:
        st.code("\n".join(wait_lines), language="text")
    st.caption(
        "Runtime settings cache："
        + ("已刷新" if result.get("runtime_settings_cache_cleared") else "未刷新")
    )
    start_record = (
        result.get("start_record") if isinstance(result.get("start_record"), dict) else {}
    )
    if start_record.get("path"):
        st.caption(f"啟動紀錄：{start_record['path']}")
    post_run_rows = maintenance_operation_post_run_check_rows(result)
    if post_run_rows:
        st.caption("後續驗證")
        st.dataframe(post_run_rows, width="stretch", hide_index=True)
        commands = [row["指令"] for row in post_run_rows if row.get("指令") and row["指令"] != "-"]
        if commands:
            st.code("\n".join(commands), language="bash")
        render_post_run_diagnostic_actions(post_run_rows)


def render_post_run_diagnostic_actions(post_run_rows: list[dict]) -> None:
    action_rows = maintenance_operation_post_run_diagnostic_action_rows(post_run_rows)
    if not action_rows:
        return
    st.caption("可直接執行的後續診斷")
    for action in action_rows:
        action_id = str(action.get("id") or "").strip()
        label = str(action.get("label") or action_id or "後續診斷")
        purpose = str(action.get("purpose") or "").strip()
        command = str(action.get("command") or "").strip()
        action_confirmed = st.checkbox(
            f"我了解這會送出「{label}」後續診斷背景任務",
            value=False,
            key=f"maintenance_post_run_diagnostic_confirm_{action_id}",
        )
        if not action_confirmed:
            hint = "勾選確認後才會啟用後續診斷，避免誤觸後續診斷。"
            if purpose:
                hint += f" 用途：{purpose}"
            st.caption(hint)
        if st.button(
            f"執行 {label}",
            key=f"maintenance_post_run_diagnostic_{action_id}",
            disabled=not action_confirmed,
            help=command or purpose or None,
        ):
            submit_api_task(
                f"/tasks/maintenance-diagnostic/{action_id}",
                {},
                task_state_key=LAST_POST_RUN_DIAGNOSTIC_TASK_KEY,
                status_state_keys=("refresh_maintenance_diagnostic_task_status_status",),
                success_message="已送出後續診斷背景任務",
                error_message="後續診斷執行失敗",
                task_type_state_key="last_post_run_diagnostic_type",
                task_type=str(action_id),
            )
    last_task_id = st.session_state.get(LAST_POST_RUN_DIAGNOSTIC_TASK_KEY)
    if last_task_id:
        with st.expander("後續診斷背景任務狀態", expanded=True):
            task_status = render_task_status_panel(
                task_id=str(last_task_id),
                refresh_key="refresh_maintenance_diagnostic_task_status",
                task_state_key=LAST_POST_RUN_DIAGNOSTIC_TASK_KEY,
            )
            result = task_result_payload(task_status)
            if result:
                render_post_run_diagnostic_result(result)


def task_result_payload(task_status: dict | None) -> dict:
    if not isinstance(task_status, dict):
        return {}
    result = task_status.get("result")
    if not isinstance(result, dict):
        return {}
    nested_result = result.get("result")
    return nested_result if isinstance(nested_result, dict) else result


def render_post_run_diagnostic_result(result: dict) -> None:
    status = str(result.get("status") or "")
    message = str(result.get("message") or status or "診斷完成")
    label = str(result.get("label") or result.get("id") or "後續診斷")
    st.caption(f"後續診斷結果：{label}")
    if status == "success":
        st.success(message)
    elif status in {"failed", "timeout"}:
        st.warning(message)
    else:
        st.info(message)
    summary_rows = (
        result.get("summary_rows") if isinstance(result.get("summary_rows"), list) else []
    )
    if summary_rows:
        st.caption("診斷摘要")
        st.dataframe(summary_rows, width="stretch", hide_index=True)
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
