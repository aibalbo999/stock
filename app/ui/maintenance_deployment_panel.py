from __future__ import annotations

import streamlit as st

from app.ui.api_actions import run_api_action_or_none
from app.ui.api_client import api_post
from app.ui.external_deployment_diagnostics import (
    external_deployment_env_check_detail_rows,
    external_deployment_env_check_summary_rows,
    external_deployment_env_key_rows,
    external_deployment_env_resolution_rows,
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


def render_external_deployment_panel(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
    maintenance_operations: dict | None = None,
    external_env_check: dict | None = None,
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
    with st.expander("外部部署選配狀態", expanded=bool(external_warning_rows)):
        deploy = (
            upgrade_audit.get("deployment")
            if isinstance(upgrade_audit.get("deployment"), dict)
            else {}
        )
        deploy_cols = st.columns(4)
        deploy_cols[0].metric(
            "部署狀態", deploy.get("status") or upgrade_audit.get("deployment_status") or "-"
        )
        deploy_cols[1].metric("Ready", int(deploy.get("ready") or 0))
        deploy_cols[2].metric("Warnings", int(deploy.get("warnings") or 0))
        deploy_cols[3].metric("Failures", int(deploy.get("failures") or 0))
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


def maintenance_operation_rows(maintenance_operations: dict) -> list[dict]:
    operations = (
        maintenance_operations.get("operations")
        if isinstance(maintenance_operations.get("operations"), list)
        else []
    )
    return [
        {
            "操作": operation.get("label") or operation.get("id") or "-",
            "狀態": "需確認" if operation.get("requires_confirmation") else "可執行",
            "作用範圍": operation.get("scope") or "-",
            "說明": operation.get("description") or "-",
            "指令": operation.get("display_command") or "-",
            "Timeout": int(operation.get("timeout_seconds") or 0),
        }
        for operation in operations
        if isinstance(operation, dict)
    ]


def recommended_maintenance_operation_id(
    maintenance_operations: dict,
    resolution_rows: list[dict],
) -> str:
    operation_ids = {
        str(operation.get("id") or "")
        for operation in maintenance_operations.get("operations") or []
        if isinstance(operation, dict)
        and operation.get("id")
        and operation.get("mutates_local_state")
    }
    local_rows = [
        row
        for row in resolution_rows
        if isinstance(row, dict) and int(row.get("本機可套用") or 0) > 0
    ]
    if not local_rows:
        return ""
    local_text = "\n".join(
        str(row.get("本機指令") or row.get("建議動作") or "")
        for row in local_rows
    )
    if (
        "start_local_dependencies_with_unlocker" in operation_ids
        and "--prefer-unlocker" in local_text
    ):
        return "start_local_dependencies_with_unlocker"
    if "start_local_dependencies" in operation_ids:
        return "start_local_dependencies"
    return ""


def maintenance_operation_recommendation_caption(
    maintenance_operations: dict,
    recommended_operation_id: str,
) -> str:
    if not recommended_operation_id:
        return ""
    operation = next(
        (
            item
            for item in maintenance_operations.get("operations") or []
            if isinstance(item, dict) and item.get("id") == recommended_operation_id
        ),
        {},
    )
    if not operation:
        return ""
    label = str(operation.get("label") or recommended_operation_id)
    command = str(operation.get("display_command") or "-")
    return f"建議操作：{label}；會預選此操作，確認後才會執行。指令：{command}"


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
        result = run_api_action_or_none(
            lambda: api_post(
                f"/maintenance/operations/{selected_operation_id}/run",
                {"confirmed": True},
                timeout=300,
            ),
            error_message="維護操作執行失敗",
        )
        if isinstance(result, dict):
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
    start_record = (
        result.get("start_record") if isinstance(result.get("start_record"), dict) else {}
    )
    if start_record.get("path"):
        st.caption(f"啟動紀錄：{start_record['path']}")
