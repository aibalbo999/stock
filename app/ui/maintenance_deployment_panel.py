from __future__ import annotations

from html import escape

import streamlit as st

from app.ui import maintenance_operation_controls
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
    structured_filing_free_validation_command_block,
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
from app.ui.maintenance_operation_controls import (
    LAST_MAINTENANCE_OPERATION_TASK_KEY,
    LAST_POST_RUN_DIAGNOSTIC_TASK_KEY,
    task_result_payload as _task_result_payload,
)
from app.ui.maintenance_status import maintenance_overview_status_label

__all__ = [
    "LAST_MAINTENANCE_OPERATION_TASK_KEY",
    "LAST_POST_RUN_DIAGNOSTIC_TASK_KEY",
    "_render_maintenance_operations",
    "_render_post_run_diagnostic_actions",
    "_task_result_payload",
    "external_deployment_metric_values",
    "external_deployment_effective_gap_rows",
    "maintenance_operation_post_run_check_rows",
    "maintenance_operation_post_run_diagnostic_action_rows",
    "maintenance_operation_recommendation_caption",
    "maintenance_operation_rows",
    "recommended_maintenance_operation_id",
    "render_external_deployment_panel",
]


def external_deployment_metric_values(upgrade_audit: dict) -> list[dict[str, object]]:
    deploy = (
        upgrade_audit.get("deployment")
        if isinstance(upgrade_audit.get("deployment"), dict)
        else {}
    )
    return [
        {
            "label": "部署狀態",
            "value": maintenance_overview_status_label(
                deploy.get("status") or upgrade_audit.get("deployment_status")
            ),
        },
        {"label": "已通過", "value": int(deploy.get("ready") or 0)},
        {"label": "提醒", "value": int(deploy.get("warnings") or 0)},
        {"label": "需處理", "value": int(deploy.get("failures") or 0)},
    ]


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
    structured_api_free_validation_commands = structured_filing_free_validation_command_block(
        upgrade_audit
    )
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
        st.markdown(
            _external_deployment_operator_summary_html(operator_summary),
            unsafe_allow_html=True,
        )
        deploy_cols = st.columns(4)
        for column, metric in zip(
            deploy_cols,
            external_deployment_metric_values(upgrade_audit),
            strict=False,
        ):
            column.metric(metric["label"], metric["value"])
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
            st.caption("外部部署啟用檢查清單")
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
            if structured_api_free_validation_commands:
                st.caption("結構化文件 API 免費驗證指令")
                st.code(structured_api_free_validation_commands, language="bash")
            if external_smoke_commands:
                st.caption("單項診斷指令")
                st.code("\n".join(external_smoke_commands), language="bash")
            st.caption("正式部署整合檢查")
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
    maintenance_operation_controls.st = st
    maintenance_operation_controls.submit_api_task = submit_api_task
    maintenance_operation_controls.render_maintenance_operations(
        maintenance_operations,
        recommended_operation_id=recommended_operation_id,
    )


def _render_post_run_diagnostic_actions(post_run_rows: list[dict]) -> None:
    maintenance_operation_controls.st = st
    maintenance_operation_controls.submit_api_task = submit_api_task
    maintenance_operation_controls.render_post_run_diagnostic_actions(post_run_rows)
