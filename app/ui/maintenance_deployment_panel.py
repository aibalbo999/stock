from __future__ import annotations

import streamlit as st

from app.ui.external_deployment_diagnostics import (
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
        if local_dependency_start_rows:
            st.caption("最近本機依賴啟動")
            st.dataframe(local_dependency_start_rows, width="stretch", hide_index=True)
        if local_dependency_repair_plan_rows:
            st.caption("本機依賴修復指引")
            st.dataframe(local_dependency_repair_plan_rows, width="stretch", hide_index=True)
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
