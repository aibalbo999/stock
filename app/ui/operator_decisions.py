from __future__ import annotations

from typing import Any

from app.ui.data_gap_actions import data_gap_action_items
from app.ui.incident_inbox import incident_inbox_items, top_incidents
from app.ui.operator_status import quota_operator_summary
from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


REPORT_DETAIL_KEYS = {
    "quality_gate",
    "tickers",
    "candidate_whitelist",
    "auto_follow_up",
    "promoted_tickers",
}


def operator_next_best_action(
    service_snapshot: dict | None,
    task_summary: dict | None,
    quota: dict | None,
    reports: list[dict] | None,
    report_result: dict | None = None,
    follow_up_plan: dict | None = None,
) -> dict[str, Any]:
    latest_report = _latest_report(reports)
    report_payload = _dict_value(report_result)
    has_report_detail = _has_report_detail_payload(report_payload)
    lifecycle = latest_report_lifecycle(report_payload, follow_up_plan) if has_report_detail else {}
    incidents = incident_inbox_items(service_snapshot, task_summary, quota, lifecycle)
    queue_incident = _first_incident(incidents, "task_queue", severity="critical")
    if queue_incident:
        return _action(
            state="blocked",
            priority=1,
            title="先修復背景任務",
            reason=queue_incident["impact"],
            risk="未修復前，分析、補強與資料刷新可能卡住。",
            impact="恢復所有背景任務提交與處理能力。",
            action_label="查看維護",
            route_hint="settings:maintenance",
            source_ids=[queue_incident["source"]],
        )

    report_id = _report_id(report_payload, latest_report)
    if not latest_report and not has_report_detail:
        return _action(
            state="attention",
            priority=3,
            title="先建立最新版報告",
            reason="目前沒有可閱讀的最新版報告。",
            risk="沒有報告時，資料補強與維護訊號缺少投資脈絡。",
            impact="建立第一份可追蹤的分析基準。",
            action_label="建立分析",
            route_hint="analysis",
            source_ids=[],
        )

    if not has_report_detail:
        return _action(
            state="attention",
            priority=3,
            title="先讀取最新版報告狀態",
            reason="目前只有報告列表摘要，尚未取得品質門檻與補強狀態。",
            risk="只靠列表摘要無法判斷最新版報告是否可直接採信。",
            impact="讀取完整報告狀態後再決定閱讀、補強或維護。",
            action_label="讀取狀態",
            route_hint=f"report:{report_id}" if report_id is not None else "report_center",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    quality_stage = stage_by_key(lifecycle, "quality")
    if lifecycle.get("overall_state") == "blocked" and quality_stage.get("state") == "blocked":
        return _action(
            state="blocked",
            priority=4,
            title="先確認報告可信度",
            reason="最新版報告目前不可直接採信。",
            risk="直接閱讀可能把候選不足或正式分析 0 檔誤判為投資結論。",
            impact="確認品質阻塞點，再決定補資料或重新分析。",
            action_label="查看報告生命週期",
            route_hint=f"report:{report_id}" if report_id is not None else "report_center",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    if quality_stage.get("state") == "attention":
        return _action(
            state="attention",
            priority=4,
            title="先確認報告品質警示",
            reason=quality_stage.get("detail") or "最新版報告品質門檻有警示。",
            risk="直接閱讀可能忽略品質門檻保留事項。",
            impact="先確認品質警示，再決定是否閱讀或補強。",
            action_label="查看報告生命週期",
            route_hint=f"report:{report_id}" if report_id is not None else "report_center",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    data_stage = stage_by_key(lifecycle, "data")
    if data_stage.get("state") == "attention":
        data_gap_action = _primary_data_gap_action(report_payload, follow_up_plan)
        if data_gap_action:
            action_label = _text(data_gap_action.get("action_label"), default="補強資料")
            return _action(
                state="attention",
                priority=5,
                title=f"先{action_label}",
                reason=data_gap_action.get("impact") or data_stage.get("detail") or "最新版報告仍有必要資料缺口。",
                risk="未補強前，報告結論需要保留資料限制。",
                impact=_data_gap_action_impact(data_gap_action),
                action_label=action_label,
                route_hint=data_gap_action.get("route_hint") or "data_enrichment",
                source_ids=_data_gap_action_source_ids(data_gap_action, report_id),
            )
        return _action(
            state="attention",
            priority=5,
            title="先補強最新版報告資料",
            reason=data_stage.get("detail") or "最新版報告仍有必要資料缺口。",
            risk="未補強前，報告結論需要保留資料限制。",
            impact="補齊股價、財務、估值或公司文件後重跑最新版報告。",
            action_label="補強資料",
            route_hint="data_enrichment",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    if lifecycle.get("overall_state") == "running":
        return _action(
            state="attention",
            priority=6,
            title="等待補強完成",
            reason="補強或重跑任務正在背景執行。",
            risk="任務完成前閱讀可能不是最新結論。",
            impact="確認任務完成後，只保留最新報告版本。",
            action_label="查看補強任務",
            route_hint="settings:maintenance",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    critical_incident = _first_critical_incident(incidents)
    if critical_incident:
        return _action(
            state="blocked",
            priority=7,
            title=critical_incident["title"],
            reason=critical_incident["impact"],
            risk="未處理此事件前，系統輸出可能不完整或任務可能失敗。",
            impact=critical_incident["next_action"],
            action_label="查看事件",
            route_hint=critical_incident["route_hint"],
            source_ids=[critical_incident["source"]],
        )

    quota_payload = _dict_value(quota)
    if not quota_payload:
        return _action(
            state="attention",
            priority=8,
            title="確認 AI 額度狀態",
            reason="目前尚未取得 AI 額度資訊。",
            risk="缺少額度狀態時，送出高成本任務可能失敗或降級。",
            impact="確認建議模型與 fallback 後再送出高成本任務。",
            action_label="查看額度",
            route_hint="settings:ai_quota",
            source_ids=[],
        )

    if quota_payload:
        quota_summary = quota_operator_summary(quota_payload)
        if quota_summary.get("state") != "ready":
            return _action(
                state="attention",
                priority=8,
                title="等待額度或查看 fallback",
                reason=f"目前建議模型 {quota_summary.get('recommended_model') or '-'} 額度不足或不可用。",
                risk="立即送出深度分析可能降級、排隊或失敗。",
                impact="確認模型 fallback 後再送出高成本任務。",
                action_label="查看額度",
                route_hint="settings:ai_quota",
                source_ids=[quota_summary.get("recommended_model") or "-"],
            )

    return _action(
        state="ready",
        priority=10,
        title="閱讀最新版報告",
        reason="背景任務、品質門檻與必補資料缺口都沒有阻塞。",
        risk="仍需把報告視為研究輔助，不是買賣指令。",
        impact="直接閱讀目前系統保留的最新版結論。",
        action_label="讀報告",
        route_hint=f"report:{report_id}" if report_id is not None else "report_center",
        source_ids=[f"report:{report_id}"] if report_id is not None else [],
    )


def operator_secondary_actions(
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
    primary = primary_action or operator_next_best_action(
        service_snapshot,
        task_summary,
        quota,
        reports,
        report_result,
        follow_up_plan,
    )
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
        }
        for incident in incidents
        if not _incident_matches_primary(incident, primary)
    ]
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
    return _dedupe_secondary_actions(secondary)[:3]


def _action(
    *,
    state: str,
    priority: int,
    title: str,
    reason: str,
    risk: str,
    impact: str,
    action_label: str,
    route_hint: str,
    source_ids: list[Any],
) -> dict[str, Any]:
    return {
        "state": state,
        "priority": priority,
        "title": title,
        "reason": reason,
        "risk": risk,
        "impact": impact,
        "action_label": action_label,
        "route_hint": route_hint,
        "source_ids": [str(source_id) for source_id in source_ids if str(source_id).strip()],
    }


def _first_incident(
    incidents: list[dict],
    category: str,
    *,
    severity: str | None = None,
) -> dict:
    for incident in incidents:
        if incident.get("category") != category:
            continue
        if severity is not None and incident.get("severity") != severity:
            continue
        return incident
    return {}


def _first_critical_incident(incidents: list[dict]) -> dict:
    for incident in incidents:
        if incident.get("severity") == "critical" and incident.get("category") not in {
            "task_queue",
            "report_quality",
        }:
            return incident
    return {}


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


def _primary_data_gap_action(report_payload: dict, follow_up_plan: dict | None) -> dict:
    items = data_gap_action_items(report_payload, follow_up_plan)
    for item in items:
        if item.get("purpose") == "required" and item.get("operation") != "report_follow_up":
            return item
    for item in items:
        if item.get("purpose") == "required":
            return item
    for item in items:
        if item.get("operation") != "report_follow_up":
            return item
    return {}


def _data_gap_action_impact(action: dict) -> str:
    impact = _text(action.get("impact"), default="補強最新版報告資料缺口。")
    post_action_hint = _text(action.get("post_action_hint"))
    if post_action_hint and post_action_hint not in impact:
        return f"{impact}；{post_action_hint}"
    return impact


def _data_gap_action_source_ids(action: dict, report_id: Any) -> list[Any]:
    source_ids: list[Any] = []
    if report_id is not None:
        source_ids.append(f"report:{report_id}")
    source_ids.extend(action.get("tickers") or [])
    return source_ids


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


def _latest_report(reports: list[dict] | None) -> dict:
    if not isinstance(reports, list):
        return {}
    for report in reports:
        if isinstance(report, dict):
            return report
    return {}


def _has_report_detail_payload(report: dict) -> bool:
    return bool(report) and any(key in report for key in REPORT_DETAIL_KEYS)


def _report_id(report_payload: dict, latest_report: dict) -> Any:
    for report in (report_payload, latest_report):
        if not isinstance(report, dict):
            continue
        for key in ("report_id", "id"):
            if report.get(key) is not None:
                return report[key]
    return None


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
