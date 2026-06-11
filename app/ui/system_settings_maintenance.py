from __future__ import annotations

from html import escape

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.dashboard_core import render_section_header
from app.ui.incident_inbox import (
    incident_counts,
    incident_inbox_items,
)
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
    render_submission_guard_panel,
    render_upgrade_audit_panel,
)
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.report_lifecycle import latest_report_lifecycle


def render_maintenance_tab() -> None:
    render_section_header("維護", "一般使用不需要查看；只有資料異常或服務連線問題時使用。")
    maintenance_focus = _consume_pending_maintenance_focus()
    external_deployment_focus = _consume_pending_external_deployment_focus()
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

    external_deployment_rendered = False
    if maintenance_focus == "external_deployment":
        render_external_deployment_panel(
            upgrade_audit,
            service_snapshot,
            maintenance_operations,
            external_env_check,
            focus_context=external_deployment_focus,
        )
        external_deployment_rendered = True

    latest_report_lifecycle_snapshot = _latest_report_lifecycle_for_maintenance()
    _render_incident_inbox(
        incident_inbox_items(
            service_snapshot,
            task_summary,
            llm_quota,
            latest_report_lifecycle_snapshot,
        )
    )
    if maintenance_focus == "ai_quota":
        render_ai_quota_panel(llm_quota, service_snapshot)
    if maintenance_focus == "task_observability":
        render_background_task_observability_panel(
            service_snapshot,
            task_summary,
            maintenance_diagnostics,
        )
    render_upgrade_audit_panel(upgrade_audit)
    render_optimization_progress_panel(service_snapshot)
    render_service_metrics_panel(status, service_snapshot)
    render_submission_guard_panel(service_snapshot)
    if not external_deployment_rendered:
        render_external_deployment_panel(
            upgrade_audit,
            service_snapshot,
            maintenance_operations,
            external_env_check,
        )
    if maintenance_focus != "ai_quota":
        render_ai_quota_panel(llm_quota, service_snapshot)
    render_ai_usage_panel(llm_usage_summary)
    render_report_generation_observability_panel(report_observability_summary)
    if maintenance_focus != "task_observability":
        render_background_task_observability_panel(
            service_snapshot,
            task_summary,
            maintenance_diagnostics,
        )
    render_report_quality_panel(report_quality_summary)
    render_service_details_panel(status, service_snapshot)
    render_maintenance_cleanup_panel()


def _consume_pending_maintenance_focus() -> str | None:
    focus = str(st.session_state.pop("pending_maintenance_focus", "") or "").strip()
    if focus in {"ai_quota", "task_observability", "external_deployment"}:
        return focus
    return None


def _consume_pending_external_deployment_focus() -> str | None:
    focus = str(st.session_state.pop("pending_external_deployment_focus", "") or "").strip()
    if focus in {"local_defaults", "structured_api"}:
        return focus
    return None


def _latest_report_lifecycle_for_maintenance() -> dict:
    reports = load_api_json_or_default(
        "/reports?limit=1",
        [],
        error_message="讀取維護頁最新版報告失敗",
        notify="warning",
    )
    if not isinstance(reports, list) or not reports or not isinstance(reports[0], dict):
        return {}
    report_id = reports[0].get("id")
    if report_id is None:
        return {}
    try:
        normalized_report_id = int(report_id)
    except (TypeError, ValueError):
        return {}

    report_payload = load_api_json_or_default(
        f"/reports/{normalized_report_id}",
        {},
        error_message="讀取維護頁報告生命週期失敗",
        notify="warning",
    )
    if not isinstance(report_payload, dict) or not report_payload:
        return {}
    follow_up_plan = load_api_json_or_default(
        f"/reports/{normalized_report_id}/follow-up/plan",
        {},
        error_message="讀取維護頁報告補強計畫失敗",
        notify="warning",
    )
    if not isinstance(follow_up_plan, dict):
        follow_up_plan = {}
    report_context = {
        "report_id": normalized_report_id,
        "id": report_payload.get("id", normalized_report_id),
        "title": report_payload.get("title") or reports[0].get("title"),
        "topic": report_payload.get("topic") or reports[0].get("topic"),
        "generated_at": report_payload.get("generated_at") or reports[0].get("generated_at"),
        "tickers": report_payload.get("tickers") or [],
        "request": report_payload.get("request") or {},
        "quality_gate": report_payload.get("quality_gate") or {},
        "auto_follow_up": report_payload.get("auto_follow_up") or {},
        "candidate_whitelist": report_payload.get("candidate_whitelist") or [],
        "candidate_audit": report_payload.get("candidate_audit") or {},
    }
    return latest_report_lifecycle(report_context, follow_up_plan)


def _render_incident_inbox(incidents: list[dict]) -> None:
    counts = incident_counts(incidents)
    incident_html = "\n".join(_incident_card_html(incident) for incident in incidents[:8])
    if not incident_html:
        incident_html = """<article class="incident-card is-ready">
<strong>目前沒有待處理事件</strong>
<span>背景任務、近期失敗與 AI 額度沒有主要阻塞。</span>
</article>"""
    st.markdown(
        f"""<section class="incident-inbox" aria-label="待處理事件">
<div class="incident-inbox-head">
<div>
<div class="workspace-kicker">待處理事件</div>
<h3>事件收件匣</h3>
</div>
<div class="incident-counts">
<span>Critical {counts["critical"]}</span>
<span>Warning {counts["warning"]}</span>
<span>Info {counts["info"]}</span>
</div>
</div>
</section>""",
        unsafe_allow_html=True,
    )
    _render_incident_action_controls(incidents)
    st.markdown(
        f"""<section class="incident-inbox is-list" aria-label="事件清單">
<div class="incident-list">
{incident_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _incident_card_html(incident: dict) -> str:
    return f"""<article class="incident-card is-{escape(incident.get("severity", "info"))}">
<strong>{escape(incident.get("title", "-"))}</strong>
<span>{escape(incident.get("impact", ""))}</span>
<em>{escape(incident.get("next_action", ""))}</em>
<small>{escape(incident.get("route_hint", ""))}</small>
</article>"""


def _render_incident_action_controls(incidents: list[dict]) -> None:
    actionable = [incident for incident in incidents if incident.get("route_hint")][:3]
    if not actionable:
        return
    st.markdown(
        """<section class="incident-action-controls" aria-label="事件處理操作">
<span>處理事件</span>
<strong>開啟對應頁面或任務檢視</strong>
</section>""",
        unsafe_allow_html=True,
    )
    columns = st.columns(len(actionable), gap="small")
    for index, incident in enumerate(actionable):
        with columns[index]:
            render_operator_route_button(
                {
                    "action_label": incident_action_label(incident, index),
                    "route_hint": incident.get("route_hint"),
                },
                key=f"incident_action_{index}",
                primary=index == 0,
                show_caption=False,
            )
            st.caption(str(incident.get("title") or incident.get("route_hint") or ""))


def incident_action_label(incident: dict, index: int) -> str:
    label = str(incident.get("action_label") or "").strip()
    return label or f"處理事件 {index + 1}"
