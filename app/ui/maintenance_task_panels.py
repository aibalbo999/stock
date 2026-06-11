from __future__ import annotations

import streamlit as st

from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_task_post
from app.ui.background_tasks import submit_api_task
from app.ui.task_failure_diagnostics import (
    recommended_task_retry_option,
    task_failure_action_route_rows,
    task_failure_category_daily_rows,
    task_failure_category_summary_rows,
    task_failure_drilldown_rows,
    task_operation_summary_rows,
    task_summary_alert_rows,
    task_retry_option_index,
    task_retry_options,
)
from app.ui.task_queue_diagnostics import (
    task_queue_health_alert,
    task_queue_health_rows,
    task_queue_repair_rows,
    task_queue_smoke_command,
)
from app.ui.task_status_panel import render_task_status_panel

MAINTENANCE_DIAGNOSTIC_TASK_KEY = "last_maintenance_diagnostic_task_id"


def render_background_task_observability_panel(
    service_snapshot: dict,
    task_summary: dict,
    maintenance_diagnostics: dict | None = None,
) -> None:
    with st.expander(
        "背景任務觀測",
        expanded=task_observability_expander_expanded(task_summary),
    ):
        st.caption("背景任務送出與執行狀態")
        st.dataframe(task_queue_health_rows(service_snapshot), width="stretch", hide_index=True)
        repair_rows = task_queue_repair_rows(service_snapshot)
        if repair_rows:
            st.caption("背景任務修復指引")
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


def task_observability_expander_expanded(task_summary: dict) -> bool:
    if not isinstance(task_summary, dict):
        return False
    if task_summary.get("recent_failures"):
        return True
    if task_summary.get("alerts"):
        return True
    totals = task_summary.get("totals") if isinstance(task_summary.get("totals"), dict) else {}
    return bool(
        int(totals.get("failed_count") or 0)
        or int(totals.get("stale_running_count") or 0)
    )


def _render_task_summary_alerts(task_summary: dict) -> None:
    task_alerts = task_summary_alert_rows(task_summary)
    for alert in task_alerts:
        message = str(alert.get("message") or "")
        next_steps = str(alert.get("next_steps") or "").strip()
        if next_steps and next_steps != "-":
            message = f"{message} 建議：{next_steps}"
        if alert.get("severity") == "error":
            st.error(message)
        elif alert.get("severity") == "warning":
            st.warning(message)
        elif alert.get("severity") == "success":
            st.success(message)
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
    operation_rows = task_operation_summary_rows(task_summary)
    if operation_rows:
        st.caption("任務類型")
        st.dataframe(operation_rows, width="stretch", hide_index=True)
    category_rows = task_failure_category_summary_rows(task_summary)
    if category_rows:
        st.caption("失敗原因分類")
        st.dataframe(category_rows, width="stretch", hide_index=True)
    daily_rows = task_failure_category_daily_rows(task_summary)
    if daily_rows:
        st.caption("失敗原因趨勢")
        st.dataframe(daily_rows, width="stretch", hide_index=True)


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
            st.caption("目前近期失敗沒有可自動重試的任務輸入。")
    inspect_task_id = st.session_state.get("maintenance_inspect_task_id")
    if inspect_task_id:
        st.caption("任務狀態詳情")
        render_task_status_panel(
            task_id=str(inspect_task_id),
            refresh_key="maintenance_retry_task_status",
            task_state_key="maintenance_inspect_task_id",
        )


def _render_task_retry_controls(retry_options: list[dict]) -> None:
    retry_options_by_id = {str(option["task_id"]): option for option in retry_options}
    retry_labels = {task_id: option["label"] for task_id, option in retry_options_by_id.items()}
    preferred_task_id = str(st.session_state.get("maintenance_inspect_task_id") or "").strip()
    recommended_retry_option = recommended_task_retry_option(
        retry_options,
        preferred_task_id=preferred_task_id,
    )
    if recommended_retry_option:
        _render_recommended_task_retry_control(recommended_retry_option)
    selected_retry_task_id = st.selectbox(
        "選擇要重試的失敗任務",
        options=[option["task_id"] for option in retry_options],
        format_func=lambda task_id: retry_labels.get(str(task_id), str(task_id)),
        key="maintenance_retry_task_select",
        index=task_retry_option_index(retry_options, preferred_task_id=preferred_task_id),
    )
    selected_retry_option = retry_options_by_id.get(str(selected_retry_task_id), {})
    selected_retry_guarded = bool(selected_retry_option.get("retry_guarded"))
    selected_retry_guard_message = str(selected_retry_option.get("retry_guard_message") or "")
    if selected_retry_guarded and selected_retry_guard_message:
        st.warning(selected_retry_guard_message)
    selected_retry_confirmed = st.checkbox(
        "我了解這會重試選取任務，可能消耗模型或資料源額度",
        value=False,
        key=f"maintenance_retry_selected_confirm_{selected_retry_task_id}",
    )
    if not selected_retry_guarded and not selected_retry_confirmed:
        st.caption("避免誤觸重試；確認後才可重新送出並消耗額度。")
    retry_cols = st.columns([1, 1])
    with retry_cols[0]:
        if st.button(
            "重試選取任務",
            key="maintenance_retry_failed_task",
            disabled=selected_retry_guarded or not selected_retry_confirmed,
        ):
            _submit_task_retry(str(selected_retry_task_id))
    with retry_cols[1]:
        if st.button("查看選取任務", key="maintenance_inspect_failed_task"):
            st.session_state["maintenance_inspect_task_id"] = selected_retry_task_id


def _render_recommended_task_retry_control(retry_option: dict) -> None:
    recommended_task_id = str(retry_option.get("task_id") or "")
    label = str(retry_option.get("label") or recommended_task_id or "建議任務")
    st.caption(f"建議處理：{label}")
    recommended_retry_confirmed = st.checkbox(
        "我了解這會重試建議任務，可能消耗模型或資料源額度",
        value=False,
        key=f"maintenance_retry_recommended_confirm_{recommended_task_id}",
    )
    if not recommended_retry_confirmed:
        st.caption("避免誤觸重試；確認後才會送出建議任務。")
    if st.button(
        "一鍵重試建議任務",
        key="maintenance_retry_recommended_task",
        type="primary",
        use_container_width=True,
        disabled=not recommended_retry_confirmed,
    ):
        _submit_task_retry(recommended_task_id)


def _submit_task_retry(task_id: str) -> None:
    retry_response = run_api_action_or_none(
        lambda: api_task_post(
            f"/tasks/{task_id}/retry",
            {},
        ),
        error_message="重試失敗",
    )
    if isinstance(retry_response, dict):
        retry_task_id = str(retry_response.get("task_id") or task_id)
        st.session_state["maintenance_inspect_task_id"] = retry_task_id
        st.success(f"已送出重試任務：{retry_task_id}")


def maintenance_diagnostic_action_rows(maintenance_diagnostics: dict) -> list[dict]:
    actions = (
        maintenance_diagnostics.get("actions")
        if isinstance(maintenance_diagnostics.get("actions"), list)
        else []
    )
    return [
        {
            "動作": action.get("label") or action.get("id") or "-",
            "狀態": _maintenance_diagnostic_action_status(action),
            "效果": maintenance_diagnostic_effect_label(action.get("effect")),
            "說明": action.get("description") or "-",
            "指令": action.get("display_command") or "-",
            "逾時秒數": int(action.get("timeout_seconds") or 0),
        }
        for action in actions
        if isinstance(action, dict)
    ]


def _render_maintenance_diagnostic_actions(maintenance_diagnostics: dict) -> None:
    action_rows = maintenance_diagnostic_action_rows(maintenance_diagnostics)
    actions = [
        action
        for action in maintenance_diagnostics.get("actions") or []
        if isinstance(action, dict) and action.get("id") and action.get("safe_to_run")
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
    selected_action = action_by_id.get(str(selected_action_id), {})
    selected_label = str(selected_action.get("label") or selected_action_id or "維護診斷")
    selected_command = str(selected_action.get("display_command") or "").strip()
    diagnostic_confirmed = st.checkbox(
        f"我了解這會送出「{selected_label}」維護診斷背景任務",
        value=False,
        key=f"maintenance_diagnostic_confirm_{selected_action_id}",
    )
    if not diagnostic_confirmed:
        st.caption("避免誤觸診斷；確認後才會送出背景任務。")
    if st.button(
        f"執行 {selected_label}",
        key="maintenance_run_diagnostic_action",
        disabled=not diagnostic_confirmed,
        help=selected_command or None,
    ):
        submit_api_task(
            f"/tasks/maintenance-diagnostic/{selected_action_id}",
            {},
            task_state_key=MAINTENANCE_DIAGNOSTIC_TASK_KEY,
            status_state_keys=("refresh_maintenance_diagnostic_action_status_status",),
            success_message="已送出維護診斷背景任務",
            error_message="診斷執行失敗",
            task_type_state_key="last_maintenance_diagnostic_action_type",
            task_type=str(selected_action_id),
        )
    last_task_id = st.session_state.get(MAINTENANCE_DIAGNOSTIC_TASK_KEY)
    if last_task_id:
        with st.expander("維護診斷背景任務狀態", expanded=True):
            task_status = render_task_status_panel(
                task_id=str(last_task_id),
                refresh_key="refresh_maintenance_diagnostic_action_status",
                task_state_key=MAINTENANCE_DIAGNOSTIC_TASK_KEY,
            )
            result = _task_result_payload(task_status)
            if result:
                _render_maintenance_diagnostic_result(result)


def _task_result_payload(task_status: dict | None) -> dict:
    if not isinstance(task_status, dict):
        return {}
    result = task_status.get("result")
    if not isinstance(result, dict):
        return {}
    nested_result = result.get("result")
    return nested_result if isinstance(nested_result, dict) else result


def _render_maintenance_diagnostic_result(result: dict) -> None:
    status = str(result.get("status") or "")
    message = str(result.get("message") or status or "診斷完成")
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


def _maintenance_diagnostic_action_status(action: dict) -> str:
    if action.get("read_only"):
        return "只讀可執行"
    if action.get("safe_to_run") and action.get("effect") == "safe_noop_task_submission":
        return "安全空跑"
    if action.get("safe_to_run") and action.get("effect") == "safe_local_neo4j_import_smoke":
        return "本機 Neo4j 匯入檢查"
    return "停用"


def maintenance_diagnostic_effect_label(value: object) -> str:
    labels = {
        "read_only": "只讀檢查",
        "safe_noop_task_submission": "安全空跑送出",
        "safe_local_neo4j_import_smoke": "本機 Neo4j 匯入檢查",
    }
    text = str(value or "").strip()
    if not text:
        return "-"
    return labels.get(text, text)
