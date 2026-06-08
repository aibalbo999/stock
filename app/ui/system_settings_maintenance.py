from __future__ import annotations

import requests
import streamlit as st

from app.ui.api_client import api_get, request_error_message
from app.ui.dashboard_core import render_section_header
from app.ui.maintenance_panels import (
    render_ai_quota_panel,
    render_ai_usage_panel,
    render_background_task_observability_panel,
    render_external_deployment_panel,
    render_maintenance_cleanup_panel,
    render_report_generation_observability_panel,
    render_report_quality_panel,
    render_service_details_panel,
    render_service_metrics_panel,
    render_upgrade_audit_panel,
)


def render_maintenance_tab() -> None:
    render_section_header("維護", "一般使用不需要查看；只有資料異常或服務連線問題時使用。")
    try:
        status = api_get("/db/status")
    except requests.RequestException as exc:
        status = {"settings": {}, "integrity": {}, "tables": {}}
        st.error(f"讀取 DB 狀態失敗：{request_error_message(exc)}")
    try:
        service_snapshot = api_get("/services/status")
    except requests.RequestException as exc:
        service_snapshot = {}
        st.error(f"讀取服務狀態失敗：{request_error_message(exc)}")
    try:
        llm_quota = api_get("/llm/quota")
    except requests.RequestException as exc:
        llm_quota = {"models": [], "totals": {}, "window": {}, "recommended_model": None}
        st.error(f"讀取 AI 額度狀態失敗：{request_error_message(exc)}")
    try:
        llm_usage_summary = api_get("/llm/usage/summary?days=7")
    except requests.RequestException as exc:
        llm_usage_summary = {"totals": {}, "by_model": [], "by_operation": [], "daily": []}
        st.error(f"讀取 AI 用量趨勢失敗：{request_error_message(exc)}")
    try:
        task_summary = api_get("/tasks/summary?days=7")
    except requests.RequestException as exc:
        task_summary = {"totals": {}, "by_status": [], "by_operation": [], "recent_failures": []}
        st.error(f"讀取背景任務觀測失敗：{request_error_message(exc)}")
    try:
        report_observability_summary = api_get("/reports/observability/summary?limit=20")
    except requests.RequestException as exc:
        report_observability_summary = {"status": "unknown", "totals": {}, "reports": [], "alerts": []}
        st.error(f"讀取報告生成觀測失敗：{request_error_message(exc)}")
    try:
        report_quality_summary = api_get("/reports/quality/summary?limit=20")
    except requests.RequestException as exc:
        report_quality_summary = {"status": "unknown", "totals": {}, "reports": [], "alerts": []}
        st.error(f"讀取報告品質總覽失敗：{request_error_message(exc)}")

    strict_upgrade_audit = st.toggle(
        "正式部署檢查",
        value=False,
        help="啟用後會把外部 Neo4j live import 也視為必備項目。",
    )
    try:
        strict_query = "true" if strict_upgrade_audit else "false"
        upgrade_audit = api_get(f"/services/upgrade-audit?strict_external={strict_query}")
    except requests.RequestException as exc:
        upgrade_audit = {"overall_status": "unknown", "warnings": [], "failures": []}
        st.error(f"讀取升級稽核失敗：{request_error_message(exc)}")

    render_upgrade_audit_panel(upgrade_audit)
    render_service_metrics_panel(status, service_snapshot)
    render_external_deployment_panel(upgrade_audit)
    render_ai_quota_panel(llm_quota, service_snapshot)
    render_ai_usage_panel(llm_usage_summary)
    render_report_generation_observability_panel(report_observability_summary)
    render_background_task_observability_panel(service_snapshot, task_summary)
    render_report_quality_panel(report_quality_summary)
    render_service_details_panel(status, service_snapshot)
    render_maintenance_cleanup_panel()
