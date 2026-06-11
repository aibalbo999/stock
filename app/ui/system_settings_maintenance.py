from __future__ import annotations

from collections.abc import Iterable
from html import escape

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.dashboard_core import render_section_header
from app.ui.incident_inbox import (
    incident_counts,
    incident_inbox_items,
    top_incidents,
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
    incident_html = "\n".join(
        _incident_card_html(incident) for incident in incident_summary_cards(incidents)
    )
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
    _render_incident_priority_summary(incidents)
    _render_incident_action_controls(incidents)
    st.markdown(
        f"""<section class="incident-inbox is-list" aria-label="事件清單">
<div class="incident-list">
{incident_html}
</div>
</section>""",
        unsafe_allow_html=True,
    )


def _render_incident_priority_summary(incidents: list[dict]) -> None:
    summary = incident_action_priority_summary(incidents)
    state = escape(str(summary.get("state") or "ready"))
    st.markdown(
        f"""<section class="incident-priority-summary is-{state}" aria-label="事件可行動摘要">
<div>
<span>建議處理順序</span>
<strong>{escape(str(summary.get("title") or ""))}</strong>
<p>{escape(str(summary.get("counts_label") or ""))}</p>
</div>
<ul>
<li>{escape(str(summary.get("primary_action") or ""))}</li>
<li>{escape(str(summary.get("secondary_action") or ""))}</li>
</ul>
</section>""",
        unsafe_allow_html=True,
    )


def incident_action_priority_summary(incidents: list[dict]) -> dict[str, object]:
    counts = incident_counts(incidents)
    critical = counts["critical"]
    warning = counts["warning"]
    info = counts["info"]
    retryable_count = sum(1 for incident in incidents if incident.get("retryable"))
    task_linked_count = sum(
        1
        for incident in incidents
        if str(incident.get("route_hint") or "").strip().startswith("task:")
    )
    routed_count = sum(1 for incident in incidents if str(incident.get("route_hint") or "").strip())
    passive_count = max(0, len(incidents) - routed_count)
    counts_label = f"Critical {critical} / Warning {warning} / Info {info}"

    if not incidents:
        return {
            "state": "ready",
            "title": "目前沒有待處理事件",
            "counts_label": counts_label,
            "primary_action": "可以回到分析工作區產生最新版報告。",
            "secondary_action": "維護頁仍保留服務狀態與升級稽核供備查。",
            "retryable_count": 0,
            "task_linked_count": 0,
            "passive_count": 0,
        }

    if critical:
        state = "blocked"
        title = f"先處理 {critical} 個 Critical 事件"
    elif warning:
        state = "attention"
        title = f"先確認 {warning} 個 Warning 事件"
    else:
        state = "watch"
        title = f"追蹤 {info} 個 Info 事件"

    if retryable_count:
        primary_action = f"{retryable_count} 個可重試任務可直接在下方操作；先處理最高嚴重度項目。"
    elif task_linked_count:
        primary_action = f"{task_linked_count} 個事件已連到任務檢視；先打開任務診斷確認原因。"
    elif critical:
        primary_action = "先依下方 Critical 事件修復服務、資料來源或本機儲存。"
    else:
        primary_action = "先確認下方事件是否影響最新版報告，再決定是否需要補強。"

    secondary_action = (
        f"{task_linked_count} 個任務檢視、{routed_count} 個跳轉入口，"
        f"{passive_count} 個為歷史趨勢/觀測。"
    )
    return {
        "state": state,
        "title": title,
        "counts_label": counts_label,
        "primary_action": primary_action,
        "secondary_action": secondary_action,
        "retryable_count": retryable_count,
        "task_linked_count": task_linked_count,
        "passive_count": passive_count,
    }


def incident_summary_cards(incidents: list[dict], limit: int = 8) -> list[dict]:
    grouped: dict[tuple[str, ...], list[dict]] = {}
    for incident in incidents:
        grouped.setdefault(_incident_summary_key(incident), []).append(incident)

    summaries: list[dict] = []
    for group in grouped.values():
        representative = dict(top_incidents(group, limit=1)[0])
        route_hints = _unique_texts(row.get("route_hint") for row in group)
        sources = _unique_texts(row.get("source") or row.get("id") for row in group)
        repeat_count = len(group)
        representative["repeat_count"] = repeat_count
        representative["hidden_count"] = max(0, repeat_count - 1)
        representative["route_hints"] = route_hints
        representative["source_ids"] = sources
        summaries.append(representative)

    return top_incidents(summaries, limit=limit)


def _incident_summary_key(incident: dict) -> tuple[str, ...]:
    return (
        str(incident.get("severity") or "").strip(),
        str(incident.get("category") or "").strip(),
        str(incident.get("title") or "").strip(),
        str(incident.get("impact") or "").strip(),
        str(incident.get("next_action") or "").strip(),
        str(incident.get("action_label") or "").strip(),
        str(bool(incident.get("retryable"))),
    )


def _unique_texts(values: Iterable[object]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip() if value is not None else ""
        if not text or text in seen:
            continue
        seen.add(text)
        selected.append(text)
    return selected


def _incident_card_html(incident: dict) -> str:
    repeat_count = _incident_count_value(incident.get("repeat_count"), default=1)
    hidden_count = _incident_count_value(
        incident.get("hidden_count"),
        default=max(0, repeat_count - 1),
    )
    repeat_badge = ""
    if repeat_count > 1:
        repeat_badge = (
            f'<span class="incident-repeat-badge">同類事件 {escape(str(repeat_count))} 筆</span>'
        )
    route_hint = str(incident.get("route_hint") or "").strip()
    route_text = route_hint
    if hidden_count > 0:
        hidden_text = f"另有 {hidden_count} 筆同類事件"
        route_text = f"{route_hint}；{hidden_text}" if route_hint else hidden_text
    return f"""<article class="incident-card is-{escape(str(incident.get("severity") or "info"))}">
<div class="incident-card-head">
<strong>{escape(str(incident.get("title") or "-"))}</strong>
{repeat_badge}
</div>
<span>{escape(str(incident.get("impact") or ""))}</span>
<em>{escape(str(incident.get("next_action") or ""))}</em>
<small>{escape(route_text)}</small>
</article>"""


def _incident_count_value(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _render_incident_action_controls(incidents: list[dict]) -> None:
    actionable = incident_action_summaries(incidents)
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
            st.caption(incident_action_caption(incident))


def incident_action_summaries(incidents: list[dict], limit: int = 3) -> list[dict]:
    return [
        incident
        for incident in incident_summary_cards(incidents, limit=limit)
        if incident.get("route_hint")
    ][:limit]


def incident_action_caption(incident: dict) -> str:
    title = str(incident.get("title") or incident.get("route_hint") or "").strip()
    repeat_count = _incident_count_value(incident.get("repeat_count"), default=1)
    if repeat_count > 1:
        repeat_text = f"同類事件 {repeat_count} 筆"
        return f"{title}｜{repeat_text}" if title else repeat_text
    return title


def incident_action_label(incident: dict, index: int) -> str:
    label = str(incident.get("action_label") or "").strip()
    return label or f"處理事件 {index + 1}"
