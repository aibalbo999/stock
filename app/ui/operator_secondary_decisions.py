from __future__ import annotations

from typing import Any

from app.ui.incident_inbox import incident_inbox_items, top_incidents
from app.ui.operator_decision_support import (
    dict_value as _dict_value,
    has_report_detail_payload as _has_report_detail_payload,
    latest_report as _latest_report,
    report_id as _report_id,
)
from app.ui.operator_optimization_actions import (
    optimization_free_validation_action as _optimization_free_validation_action,
    optimization_local_defaults_action as _optimization_local_defaults_action,
)
from app.ui.report_lifecycle import latest_report_lifecycle


MAX_SECONDARY_ACTIONS = 4


def build_operator_secondary_actions(
    service_snapshot: dict | None,
    task_summary: dict | None,
    quota: dict | None,
    reports: list[dict] | None,
    report_result: dict | None = None,
    follow_up_plan: dict | None = None,
    primary_action: dict | None = None,
) -> list[dict[str, Any]]:
    latest_report = _latest_report(reports)
    report_payload = _dict_value(report_result)
    has_report_detail = _has_report_detail_payload(report_payload)
    lifecycle = latest_report_lifecycle(report_payload, follow_up_plan) if has_report_detail else {}
    primary = primary_action or {}
    incidents = top_incidents(
        incident_inbox_items(service_snapshot, task_summary, quota, lifecycle),
        limit=10,
    )
    secondary = [
        {
            "title": incident["title"],
            "detail": incident["next_action"],
            "state": _incident_state(incident),
            "route_hint": incident["route_hint"],
            "action_label": incident.get("action_label") or "查看事件",
        }
        for incident in incidents
        if not _incident_matches_primary(incident, primary)
    ]
    local_defaults_action = _optimization_local_defaults_action(service_snapshot)
    if local_defaults_action:
        _append_secondary_action(secondary, primary, local_defaults_action)
    free_validation_action = _optimization_free_validation_action(service_snapshot)
    if free_validation_action:
        _append_secondary_action(secondary, primary, free_validation_action)
    report_id = _report_id(report_payload, latest_report)
    if report_id is not None:
        _append_secondary_action(
            secondary,
            primary,
            {
                "title": "查看報告生命週期",
                "detail": lifecycle.get("trust_label") or "確認最新版報告狀態",
                "state": lifecycle.get("overall_state") or "attention",
                "route_hint": f"report:{report_id}",
                "source_ids": [f"report:{report_id}"],
            },
        )
    _append_secondary_action(
        secondary,
        primary,
        {
            "title": "資料缺口行動地圖",
            "detail": "查看目前補資料動作能改善哪些報告缺口。",
            "state": "attention",
            "route_hint": "data_enrichment",
            "source_ids": [],
        },
    )
    return _dedupe_secondary_actions(secondary)[:MAX_SECONDARY_ACTIONS]


def _incident_state(incident: dict) -> str:
    if incident.get("severity") == "critical":
        return "blocked"
    if incident.get("severity") == "warning":
        return "attention"
    return "ready"


def _dedupe_secondary_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for action in actions:
        key = (action.get("title"), action.get("route_hint"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _append_secondary_action(
    secondary: list[dict[str, Any]],
    primary_action: dict,
    action: dict[str, Any],
) -> None:
    if _secondary_action_matches_primary(action, primary_action):
        return
    secondary.append({key: value for key, value in action.items() if key != "source_ids"})


def _incident_matches_primary(incident: dict, primary_action: dict) -> bool:
    source = str(incident.get("source") or "").strip()
    return (
        bool(primary_action)
        and (
            incident.get("title") == primary_action.get("title")
            or source in set(primary_action.get("source_ids") or [])
        )
    )


def _secondary_action_matches_primary(action: dict, primary_action: dict) -> bool:
    action_sources = {str(source) for source in action.get("source_ids") or [] if str(source).strip()}
    primary_sources = set(primary_action.get("source_ids") or [])
    return (
        bool(primary_action)
        and (
            action.get("title") == primary_action.get("title")
            or action.get("route_hint") == primary_action.get("route_hint")
            or bool(action_sources & primary_sources)
        )
    )
