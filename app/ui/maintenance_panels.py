from __future__ import annotations

import streamlit as st

from app.ui.maintenance_ai_panels import (
    render_ai_quota_panel,
    render_ai_usage_panel,
)
from app.ui.maintenance_cleanup_panel import render_maintenance_cleanup_panel
from app.ui.maintenance_deployment_panel import render_external_deployment_panel
from app.ui.maintenance_status import (
    maintenance_service_metrics,
    upgrade_audit_html,
    upgrade_audit_rows,
)
from app.ui.maintenance_task_panels import render_background_task_observability_panel
from app.ui.report_observability_panel import render_report_observability_panel

__all__ = [
    "render_ai_quota_panel",
    "render_ai_usage_panel",
    "render_background_task_observability_panel",
    "render_external_deployment_panel",
    "render_maintenance_cleanup_panel",
    "render_report_generation_observability_panel",
    "render_report_quality_panel",
    "render_service_details_panel",
    "render_service_metrics_panel",
    "render_upgrade_audit_panel",
]


def render_upgrade_audit_panel(upgrade_audit: dict) -> None:
    st.markdown(upgrade_audit_html(upgrade_audit), unsafe_allow_html=True)
    with st.expander("升級稽核明細"):
        st.dataframe(upgrade_audit_rows(upgrade_audit), width="stretch", hide_index=True)


def render_service_metrics_panel(status: dict, service_snapshot: dict) -> None:
    service_metrics = maintenance_service_metrics(status, service_snapshot)
    service_cols = st.columns(len(service_metrics))
    for column, (label, value) in zip(service_cols, service_metrics.items()):
        column.metric(label, value)


def render_report_generation_observability_panel(report_observability_summary: dict) -> None:
    with st.expander("報告生成觀測", expanded=False):
        render_report_observability_panel(report_observability_summary)


def render_report_quality_panel(report_quality_summary: dict) -> None:
    with st.expander("報告品質 Gate 總覽", expanded=False):
        quality_totals = (
            report_quality_summary.get("totals")
            if isinstance(report_quality_summary.get("totals"), dict)
            else {}
        )
        quality_cols = st.columns(5)
        quality_cols[0].metric("狀態", report_quality_summary.get("status") or "-")
        quality_cols[1].metric("最新版報告", int(quality_totals.get("report_count") or 0))
        quality_cols[2].metric("Ready", int(quality_totals.get("ready_count") or 0))
        quality_cols[3].metric("Blockers", int(quality_totals.get("blocker_count") or 0))
        quality_cols[4].metric("Warnings", int(quality_totals.get("warning_count") or 0))
        if report_quality_summary.get("alerts"):
            st.dataframe(report_quality_summary["alerts"], width="stretch", hide_index=True)
        if report_quality_summary.get("reports"):
            st.dataframe(report_quality_summary["reports"], width="stretch", hide_index=True)


def render_service_details_panel(status: dict, service_snapshot: dict) -> None:
    with st.expander("進階：服務細節"):
        st.json(status["settings"])
        st.json(status["integrity"])
        st.json(service_snapshot)
        st.dataframe(
            [{"table": table, **details} for table, details in status["tables"].items()],
            width="stretch",
            hide_index=True,
        )
