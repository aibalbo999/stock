from __future__ import annotations

from typing import Any

from app.ui.incident_inbox import incident_inbox_items, top_incidents
from app.ui.operator_status import quota_operator_summary
from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


def operator_next_best_action(
    service_snapshot: dict | None,
    task_summary: dict | None,
    quota: dict | None,
    reports: list[dict] | None,
    report_result: dict | None = None,
    follow_up_plan: dict | None = None,
) -> dict[str, Any]:
    latest_report = _latest_report(reports)
    report_payload = _dict_value(report_result) or latest_report
    lifecycle = latest_report_lifecycle(report_payload, follow_up_plan)
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

    if not latest_report and not report_payload:
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

    report_id = lifecycle.get("report_id") or latest_report.get("id")
    quality_stage = stage_by_key(lifecycle, "quality")
    if lifecycle.get("overall_state") == "blocked" and quality_stage.get("state") == "blocked":
        return _action(
            state="blocked",
            priority=5,
            title="先確認報告可信度",
            reason="最新版報告目前不可直接採信。",
            risk="直接閱讀可能把候選不足或正式分析 0 檔誤判為投資結論。",
            impact="確認品質阻塞點，再決定補資料或重新分析。",
            action_label="查看報告生命週期",
            route_hint=f"report:{report_id}" if report_id is not None else "report_center",
            source_ids=[f"report:{report_id}"] if report_id is not None else [],
        )

    data_stage = stage_by_key(lifecycle, "data")
    if data_stage.get("state") == "attention":
        return _action(
            state="attention",
            priority=4,
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

    quota_payload = _dict_value(quota)
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
) -> list[dict[str, Any]]:
    latest_report = _latest_report(reports)
    report_payload = _dict_value(report_result) or latest_report
    lifecycle = latest_report_lifecycle(report_payload, follow_up_plan)
    incidents = top_incidents(
        incident_inbox_items(service_snapshot, task_summary, quota, lifecycle),
        limit=3,
    )
    secondary = [
        {
            "title": incident["title"],
            "detail": incident["next_action"],
            "state": _incident_state(incident),
            "route_hint": incident["route_hint"],
        }
        for incident in incidents
    ]
    report_id = lifecycle.get("report_id") or latest_report.get("id")
    if report_id is not None:
        secondary.append(
            {
                "title": "查看報告生命週期",
                "detail": lifecycle.get("trust_label") or "確認最新版報告狀態",
                "state": lifecycle.get("overall_state") or "attention",
                "route_hint": f"report:{report_id}",
            }
        )
    secondary.append(
        {
            "title": "資料缺口行動地圖",
            "detail": "查看目前補資料動作能改善哪些報告缺口。",
            "state": "attention",
            "route_hint": "data_enrichment",
        }
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


def _latest_report(reports: list[dict] | None) -> dict:
    if not isinstance(reports, list):
        return {}
    for report in reports:
        if isinstance(report, dict):
            return report
    return {}


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
