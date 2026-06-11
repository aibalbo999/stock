from __future__ import annotations

from typing import Any

from app.ui.data_gap_actions import market_freshness_action_item
from app.ui.incident_inbox import incident_inbox_items
from app.ui.operator_decision_support import (
    data_gap_action_impact as _data_gap_action_impact,
    data_gap_action_source_ids as _data_gap_action_source_ids,
    dict_value as _dict_value,
    has_report_detail_payload as _has_report_detail_payload,
    healthy_read_reason as _healthy_read_reason,
    healthy_read_risk as _healthy_read_risk,
    latest_report as _latest_report,
    operator_action as _action,
    primary_data_gap_action as _primary_data_gap_action,
    report_id as _report_id,
    required_follow_up_count as _required_follow_up_count,
    retryable_failure_affecting_report as _retryable_failure_affecting_report,
    text_value as _text,
)
from app.ui.operator_secondary_decisions import MAX_SECONDARY_ACTIONS as _MAX_SECONDARY_ACTIONS
from app.ui.operator_secondary_decisions import build_operator_secondary_actions
from app.ui.operator_status import quota_operator_summary, service_status_unavailable
from app.ui.operator_task_state import (
    latest_task_running as _latest_task_running,
    latest_task_successful as _latest_task_successful,
)
from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


MAX_SECONDARY_ACTIONS = _MAX_SECONDARY_ACTIONS


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
    if service_status_unavailable(service_snapshot):
        return _action(
            state="attention",
            priority=1,
            title="確認系統狀態",
            reason="目前無法讀取系統狀態；請先到維護頁確認 API 與背景任務觀測。",
            risk="這不代表背景任務已壞掉，但暫時無法判斷新的分析或補強能否送出。",
            impact="確認系統狀態恢復後，再送出新的長時間任務。",
            action_label="查看維護",
            route_hint="settings:maintenance",
            source_ids=["services_status"],
        )

    incidents = incident_inbox_items(service_snapshot, task_summary, quota, lifecycle)
    queue_unavailable_incident = _first_incident_by_id(incidents, "task_queue_unavailable")
    if queue_unavailable_incident:
        return _action(
            state="blocked",
            priority=1,
            title="先修復背景任務",
            reason=queue_unavailable_incident["impact"],
            risk="未修復前，分析、補強與資料刷新可能卡住。",
            impact="恢復所有背景任務提交與處理能力。",
            action_label="查看維護",
            route_hint="settings:maintenance",
            source_ids=[queue_unavailable_incident["source"]],
        )

    stale_running_incident = _first_incident_by_id(
        incidents,
        "task_queue_stale_running",
        dedupe_key="task_queue:stale_running",
    )
    if stale_running_incident:
        return _action(
            state="blocked",
            priority=2,
            title="檢查卡住的背景任務",
            reason=stale_running_incident["title"],
            risk="卡住任務可能讓新的補強或報告任務排隊等待過久。",
            impact=stale_running_incident["next_action"],
            action_label=stale_running_incident.get("action_label") or "查看任務",
            route_hint=stale_running_incident["route_hint"],
            source_ids=[stale_running_incident["source"]],
        )

    queue_incident = _first_incident(incidents, "task_queue", severity="critical")
    if queue_incident:
        return _action(
            state="blocked",
            priority=1,
            title="先修復背景任務",
            reason=queue_incident["impact"],
            risk="未修復前，分析、補強與資料刷新可能卡住。",
            impact="恢復所有背景任務提交與處理能力。",
            action_label=queue_incident.get("action_label") or "查看維護",
            route_hint=queue_incident["route_hint"],
            source_ids=[queue_incident["source"]],
        )

    report_id = _report_id(report_payload, latest_report)
    if not latest_report and not has_report_detail:
        latest_running_task = _latest_task_running(task_summary)
        if latest_running_task:
            task_id = _text(latest_running_task.get("task_id"))
            return _action(
                state="attention",
                priority=3,
                title="等待最新任務完成",
                reason="最新背景任務正在執行，尚未產生可閱讀的最新版報告。",
                risk="重複送出同類任務可能造成排隊、額度消耗或資料寫入衝突。",
                impact="到維護頁查看任務進度；完成後再閱讀最新版報告或重新送出。",
                action_label="查看任務進度",
                route_hint=f"task:{task_id}" if task_id else "settings:maintenance",
                source_ids=[task_id or latest_running_task.get("id") or "latest_task"],
            )
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

    if quality_stage.get("state") == "unknown":
        return _action(
            state="attention",
            priority=4,
            title="先確認報告品質狀態",
            reason=quality_stage.get("detail") or "最新版報告尚無法判斷品質門檻。",
            risk="直接閱讀可能把未驗證 ticker 清單誤判為正式分析結果。",
            impact="確認品質門檻後再決定閱讀、補強或重跑。",
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
    if data_stage.get("state") == "attention" and _required_follow_up_count(follow_up_plan) > 0:
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

    retryable_latest_failure = _retryable_failure_affecting_report(task_summary, report_id)
    if retryable_latest_failure:
        retry_task_id = _text(retryable_latest_failure.get("task_id"))
        return _action(
            state="attention",
            priority=7,
            title="重試影響最新版報告的任務",
            reason=_text(
                retryable_latest_failure.get("error_summary"),
                default="近期有可重試任務影響最新版報告。",
            ),
            risk="未重試前，最新版報告可能沿用不完整資料或舊狀態。",
            impact=_text(
                retryable_latest_failure.get("next_action"),
                default="到維護頁重試此任務。",
            ),
            action_label="重試任務",
            route_hint=f"task:{retry_task_id}" if retry_task_id else "settings:maintenance",
            source_ids=[
                f"report:{report_id}" if report_id is not None else "",
                retry_task_id or retryable_latest_failure.get("id") or "",
            ],
        )

    critical_incident = _first_critical_incident(incidents)
    if critical_incident and _critical_incident_should_block(critical_incident, task_summary):
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
    quota_missing = not quota_payload
    if quota_payload:
        quota_summary = quota_operator_summary(quota_payload)
        if quota_summary.get("state") != "ready":
            return _action(
                state="attention",
                priority=8,
                title="等待額度或查看後援模型",
                reason=f"目前建議模型 {quota_summary.get('recommended_model') or '-'} 額度不足或不可用。",
                risk="立即送出深度分析可能降級、排隊或失敗。",
                impact="確認模型後援路由後再送出高成本任務。",
                action_label="查看額度",
                route_hint="settings:ai_quota",
                source_ids=[quota_summary.get("recommended_model") or "-"],
            )

    market_freshness_action = market_freshness_action_item(report_payload)
    if market_freshness_action:
        action_label = _text(market_freshness_action.get("action_label"), default="刷新股價")
        return _action(
            state="attention",
            priority=9,
            title=f"先{action_label}",
            reason=_text(
                market_freshness_action.get("impact"),
                default="股價資料落後資料庫最新快取。",
            ),
            risk="閱讀前未刷新股價，最新版報告可能沿用落後的價量判讀。",
            impact=_data_gap_action_impact(market_freshness_action),
            action_label=action_label,
            route_hint=market_freshness_action.get("route_hint") or "data_enrichment:market_refresh",
            source_ids=_data_gap_action_source_ids(market_freshness_action, report_id),
        )

    return _action(
        state="ready",
        priority=10,
        title="閱讀最新版報告",
        reason=_healthy_read_reason(quota_missing=quota_missing),
        risk=_healthy_read_risk(quota_missing=quota_missing),
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
    primary = primary_action or operator_next_best_action(
        service_snapshot,
        task_summary,
        quota,
        reports,
        report_result,
        follow_up_plan,
    )
    return build_operator_secondary_actions(
        service_snapshot,
        task_summary,
        quota,
        reports,
        report_result,
        follow_up_plan,
        primary_action=primary,
    )


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


def _first_incident_by_id(
    incidents: list[dict],
    incident_id: str,
    *,
    dedupe_key: str | None = None,
) -> dict:
    for incident in incidents:
        if incident.get("id") == incident_id or (
            dedupe_key is not None and incident.get("dedupe_key") == dedupe_key
        ):
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


def _critical_incident_should_block(incident: dict, task_summary: dict | None) -> bool:
    if not _latest_task_successful(task_summary):
        return True
    return not _is_task_failure_incident(incident)


def _is_task_failure_incident(incident: dict) -> bool:
    dedupe_key = _text(incident.get("dedupe_key"))
    incident_id = _text(incident.get("id"))
    return dedupe_key.startswith("failure:") or incident_id.startswith("failure_")
