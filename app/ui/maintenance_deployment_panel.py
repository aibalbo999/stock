from __future__ import annotations

from html import escape

import streamlit as st

from app.ui.background_tasks import submit_api_task
from app.ui.external_deployment_diagnostics import (
    external_deployment_enablement_summary,
    external_deployment_enablement_summary_rows,
    external_deployment_env_check_detail_rows,
    external_deployment_env_check_summary_rows,
    external_deployment_env_key_rows,
    external_deployment_env_resolution_rows,
    external_deployment_pending_gap_display_rows,
    external_deployment_readiness_rows,
    external_deployment_smoke_commands,
    external_deployment_warning_rows,
    high_risk_filing_unlocker_rows,
    local_dependency_last_start_rows,
    local_dependency_repair_rows,
    local_dependency_status_rows,
    local_neo4j_operation_rows,
    local_unlocker_operation_rows,
    structured_filing_api_operation_rows,
)
from app.ui.maintenance_deployment_presenter import (
    external_deployment_effective_gap_rows,
    external_deployment_focus_banner,
    external_deployment_operator_summary,
    maintenance_operation_post_run_check_rows,
    maintenance_operation_post_run_diagnostic_action_rows,
    maintenance_operation_recommendation_caption,
    maintenance_operation_rows,
    merge_local_action_projections,
    recommended_maintenance_operation_id,
)
from app.ui.task_status_panel import render_task_status_panel

LAST_MAINTENANCE_OPERATION_TASK_KEY = "last_maintenance_operation_task_id"
LAST_POST_RUN_DIAGNOSTIC_TASK_KEY = "last_post_run_diagnostic_task_id"


def render_external_deployment_panel(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
    maintenance_operations: dict | None = None,
    external_env_check: dict | None = None,
    focus_context: str | None = None,
) -> None:
    service_snapshot = service_snapshot or {}
    local_dependency_status = (
        service_snapshot.get("local_dependencies")
        if isinstance(service_snapshot.get("local_dependencies"), dict)
        else {}
    )
    external_readiness_rows = external_deployment_readiness_rows(
        upgrade_audit,
        local_dependency_status,
    )
    external_enablement_summary = external_deployment_enablement_summary(
        upgrade_audit,
        local_dependency_status,
    )
    external_enablement_summary_rows = external_deployment_enablement_summary_rows(
        upgrade_audit,
        local_dependency_status,
    )
    external_pending_gap_rows = external_deployment_pending_gap_display_rows(
        upgrade_audit,
        local_dependency_status,
    )
    external_warning_rows = external_deployment_warning_rows(upgrade_audit)
    external_smoke_commands = external_deployment_smoke_commands(upgrade_audit)
    external_env_key_rows = external_deployment_env_key_rows(upgrade_audit, service_snapshot)
    external_env_resolution_rows = external_deployment_env_resolution_rows(
        upgrade_audit,
        service_snapshot,
    )
    external_env_check_summary_rows = external_deployment_env_check_summary_rows(
        external_env_check or {}
    )
    high_risk_unlocker_rows = high_risk_filing_unlocker_rows(upgrade_audit)
    local_neo4j_rows = local_neo4j_operation_rows(upgrade_audit)
    local_unlocker_rows = local_unlocker_operation_rows(upgrade_audit)
    structured_api_rows = structured_filing_api_operation_rows(upgrade_audit)
    local_dependency_rows = local_dependency_status_rows(service_snapshot)
    local_dependency_start_rows = local_dependency_last_start_rows(service_snapshot)
    local_dependency_repair_plan_rows = local_dependency_repair_rows(service_snapshot)
    external_local_projection = (
        upgrade_audit.get("external_deployment_local_projection")
        if isinstance(upgrade_audit.get("external_deployment_local_projection"), dict)
        else {}
    )
    external_effective_gap_rows = external_deployment_effective_gap_rows(external_local_projection)
    optimization_progress = (
        service_snapshot.get("optimization_progress")
        if isinstance(service_snapshot.get("optimization_progress"), dict)
        else {}
    )
    local_resolution_projection = (
        optimization_progress.get("local_resolution_projection")
        if isinstance(optimization_progress.get("local_resolution_projection"), dict)
        else {}
    )
    operator_summary = external_deployment_operator_summary(
        upgrade_audit,
        external_enablement_summary,
        external_local_projection,
    )
    focus_banner = external_deployment_focus_banner(focus_context)
    if focus_banner:
        st.markdown(_external_deployment_focus_banner_html(focus_banner), unsafe_allow_html=True)
    with st.expander(
        "外部部署選配狀態",
        expanded=bool(external_warning_rows) or bool(focus_banner),
    ):
        deploy = (
            upgrade_audit.get("deployment")
            if isinstance(upgrade_audit.get("deployment"), dict)
            else {}
        )
        st.markdown(
            _external_deployment_operator_summary_html(operator_summary),
            unsafe_allow_html=True,
        )
        deploy_cols = st.columns(4)
        deploy_cols[0].metric(
            "部署狀態", deploy.get("status") or upgrade_audit.get("deployment_status") or "-"
        )
        deploy_cols[1].metric("Ready", int(deploy.get("ready") or 0))
        deploy_cols[2].metric("Warnings", int(deploy.get("warnings") or 0))
        deploy_cols[3].metric("Failures", int(deploy.get("failures") or 0))
        if external_enablement_summary.get("total"):
            enablement_cols = st.columns(4)
            enablement_cols[0].metric(
                "本機免費可補",
                int(external_enablement_summary.get("free_local_pending") or 0),
            )
            enablement_cols[1].metric(
                "本機可操作",
                int(external_enablement_summary.get("local_action_available") or 0),
            )
            enablement_cols[2].metric(
                "額度/外部選配",
                int(external_enablement_summary.get("quota_or_external_pending") or 0),
            )
            enablement_cols[3].metric(
                "需付費 API",
                int(external_enablement_summary.get("paid_external_pending") or 0),
            )
            next_action = str(external_enablement_summary.get("primary_next_action") or "")
            if next_action:
                st.caption(next_action)
        if external_enablement_summary_rows:
            st.caption("外部部署啟用摘要")
            st.dataframe(external_enablement_summary_rows, width="stretch", hide_index=True)
        if external_effective_gap_rows:
            effective_cols = st.columns(4)
            effective_cols[0].metric(
                "原始待處理",
                int(external_local_projection.get("current_pending") or 0),
            )
            effective_cols[1].metric(
                "本機可消除",
                int(external_local_projection.get("available_local_default_gap_count") or 0),
            )
            effective_cols[2].metric(
                "有效剩餘",
                int(external_local_projection.get("remaining_pending") or 0),
            )
            effective_cols[3].metric(
                "剩餘付費 API",
                int(external_local_projection.get("remaining_paid_external_pending") or 0),
            )
            if external_local_projection.get("next_action"):
                st.caption(str(external_local_projection["next_action"]))
            st.caption("有效外部缺口")
            st.dataframe(external_effective_gap_rows, width="stretch", hide_index=True)
        if external_pending_gap_rows:
            st.caption("待處理缺口分類")
            st.dataframe(external_pending_gap_rows, width="stretch", hide_index=True)
        if external_readiness_rows:
            st.caption("外部部署 readiness checklist")
            st.dataframe(external_readiness_rows, width="stretch", hide_index=True)
        if external_env_resolution_rows:
            st.caption("外部設定處理計畫")
            st.dataframe(external_env_resolution_rows, width="stretch", hide_index=True)
        if external_env_check_summary_rows:
            st.caption("目前 .env 外部部署檢查")
            st.dataframe(external_env_check_summary_rows, width="stretch", hide_index=True)
            env_check_target = st.radio(
                ".env 檢查目標",
                options=["host", "compose"],
                horizontal=True,
                key="external_env_check_target",
            )
            external_env_check_detail_rows = external_deployment_env_check_detail_rows(
                external_env_check or {},
                target=str(env_check_target),
            )
            if external_env_check_detail_rows:
                st.dataframe(external_env_check_detail_rows, width="stretch", hide_index=True)
        if external_env_key_rows:
            st.caption("外部設定缺口")
            st.dataframe(external_env_key_rows, width="stretch", hide_index=True)
        if local_dependency_start_rows:
            st.caption("最近本機依賴啟動")
            st.dataframe(local_dependency_start_rows, width="stretch", hide_index=True)
        if local_dependency_repair_plan_rows:
            st.caption("本機依賴修復指引")
            st.dataframe(local_dependency_repair_plan_rows, width="stretch", hide_index=True)
        _render_maintenance_operations(
            maintenance_operations or {},
            recommended_operation_id=recommended_maintenance_operation_id(
                maintenance_operations or {},
                external_env_resolution_rows,
                merge_local_action_projections(
                    local_resolution_projection,
                    external_local_projection,
                ),
            ),
        )
        if local_dependency_rows:
            st.caption("本機依賴狀態")
            st.dataframe(local_dependency_rows, width="stretch", hide_index=True)
        if external_warning_rows:
            st.dataframe(external_warning_rows, width="stretch", hide_index=True)
            if high_risk_unlocker_rows:
                st.caption("高風險文件 unlocker")
                st.dataframe(high_risk_unlocker_rows, width="stretch", hide_index=True)
            if local_neo4j_rows:
                st.caption("本機 Neo4j / GraphRAG 操作提示")
                st.dataframe(local_neo4j_rows, width="stretch", hide_index=True)
            if local_unlocker_rows:
                st.caption("本機 unlocker 操作提示")
                st.dataframe(local_unlocker_rows, width="stretch", hide_index=True)
            if structured_api_rows:
                st.caption("結構化文件 API 操作提示")
                st.dataframe(structured_api_rows, width="stretch", hide_index=True)
            if external_smoke_commands:
                st.caption("單項診斷指令")
                st.code("\n".join(external_smoke_commands), language="bash")
            st.caption("正式部署整合 smoke")
            st.code(
                ".venv/bin/python scripts/external_integrations_smoke.py --strict --json",
                language="bash",
            )
        else:
            st.success("外部部署選配目前沒有警示。")


def _external_deployment_focus_banner_html(banner: dict) -> str:
    return f"""<section class="maintenance-focus-banner is-{escape(str(banner.get("state", "attention")))}" aria-label="目前維護焦點">
<div>
<span>目前焦點</span>
<strong>{escape(str(banner.get("title") or "-"))}</strong>
<p>{escape(str(banner.get("detail") or ""))}</p>
</div>
<em>{escape(str(banner.get("target_caption") or ""))}</em>
</section>"""


def _external_deployment_operator_summary_html(summary: dict) -> str:
    return f"""<section class="external-deployment-operator-summary is-{escape(str(summary.get("state", "ready")))}" aria-label="外部部署選配決策摘要">
<span>外部部署選配決策摘要</span>
<strong>{escape(str(summary.get("title") or "-"))}</strong>
<p>{escape(str(summary.get("detail") or ""))}</p>
<div class="external-deployment-operator-summary-grid">
  <em>{escape(str(summary.get("local_action") or "-"))}</em>
  <em>{escape(str(summary.get("effective_remaining") or "-"))}</em>
  <em>{escape(str(summary.get("paid_external") or "-"))}</em>
</div>
<small>{escape(str(summary.get("next_step") or ""))}</small>
</section>"""


def _render_maintenance_operations(
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
            result = _task_result_payload(task_status)
            if result:
                _render_maintenance_operation_result(result)


def _render_maintenance_operation_result(result: dict) -> None:
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
        _render_post_run_diagnostic_actions(post_run_rows)


def _render_post_run_diagnostic_actions(post_run_rows: list[dict]) -> None:
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
            result = _task_result_payload(task_status)
            if result:
                _render_post_run_diagnostic_result(result)


def _task_result_payload(task_status: dict | None) -> dict:
    if not isinstance(task_status, dict):
        return {}
    result = task_status.get("result")
    if not isinstance(result, dict):
        return {}
    nested_result = result.get("result")
    return nested_result if isinstance(nested_result, dict) else result


def _render_post_run_diagnostic_result(result: dict) -> None:
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
