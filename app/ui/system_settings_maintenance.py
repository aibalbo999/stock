from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.dashboard_core import render_section_header
from app.ui.maintenance_panels import (
    render_ai_quota_panel,
    render_ai_usage_panel,
    render_background_task_observability_panel,
    render_external_deployment_panel,
    render_maintenance_cleanup_panel,
    render_optimization_progress_panel,
    render_report_generation_observability_panel,
    render_report_quality_panel,
    render_service_details_panel,
    render_service_metrics_panel,
    render_upgrade_audit_panel,
)


def render_maintenance_tab() -> None:
    render_section_header("維護", "一般使用不需要查看；只有資料異常或服務連線問題時使用。")
    status = load_api_json_or_default(
        "/db/status",
        {"settings": {}, "integrity": {}, "tables": {}},
        error_message="讀取 DB 狀態失敗",
    )
    service_snapshot = load_api_json_or_default(
        "/services/status",
        {},
        error_message="讀取服務狀態失敗",
    )
    llm_quota = load_api_json_or_default(
        "/llm/quota",
        {"models": [], "totals": {}, "window": {}, "recommended_model": None},
        error_message="讀取 AI 額度狀態失敗",
    )
    llm_usage_summary = load_api_json_or_default(
        "/llm/usage/summary?days=7",
        {"totals": {}, "by_model": [], "by_operation": [], "daily": []},
        error_message="讀取 AI 用量趨勢失敗",
    )
    task_summary = load_api_json_or_default(
        "/tasks/summary?days=7",
        {"totals": {}, "by_status": [], "by_operation": [], "recent_failures": []},
        error_message="讀取背景任務觀測失敗",
    )
    maintenance_diagnostics = load_api_json_or_default(
        "/maintenance/diagnostics",
        {"actions": []},
        error_message="讀取維護診斷動作失敗",
    )
    maintenance_operations = load_api_json_or_default(
        "/maintenance/operations",
        {"operations": []},
        error_message="讀取維護操作失敗",
    )
    external_env_check = load_api_json_or_default(
        "/services/external-deployment/env-check",
        {"status": "unknown", "checks": {}},
        error_message="讀取外部部署 .env 檢查失敗",
    )
    report_observability_summary = load_api_json_or_default(
        "/reports/observability/summary?limit=20",
        {"status": "unknown", "totals": {}, "reports": [], "alerts": []},
        error_message="讀取報告生成觀測失敗",
    )
    report_quality_summary = load_api_json_or_default(
        "/reports/quality/summary?limit=20",
        {"status": "unknown", "totals": {}, "reports": [], "alerts": []},
        error_message="讀取報告品質總覽失敗",
    )

    strict_upgrade_audit = st.toggle(
        "正式部署檢查",
        value=False,
        help="啟用後會把外部 Neo4j live import 也視為必備項目。",
    )
    strict_query = "true" if strict_upgrade_audit else "false"
    upgrade_audit = load_api_json_or_default(
        f"/services/upgrade-audit?strict_external={strict_query}",
        {"overall_status": "unknown", "warnings": [], "failures": []},
        error_message="讀取升級稽核失敗",
    )

    render_upgrade_audit_panel(upgrade_audit)
    render_optimization_progress_panel(service_snapshot)
    render_service_metrics_panel(status, service_snapshot)
    render_external_deployment_panel(
        upgrade_audit,
        service_snapshot,
        maintenance_operations,
        external_env_check,
    )
    render_ai_quota_panel(llm_quota, service_snapshot)
    render_ai_usage_panel(llm_usage_summary)
    render_report_generation_observability_panel(report_observability_summary)
    render_background_task_observability_panel(
        service_snapshot,
        task_summary,
        maintenance_diagnostics,
    )
    render_report_quality_panel(report_quality_summary)
    render_service_details_panel(status, service_snapshot)
    render_maintenance_cleanup_panel()
