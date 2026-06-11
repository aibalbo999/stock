from __future__ import annotations

from typing import Any

from app.ui.data_gap_actions import data_gap_action_items, market_freshness_action_item
from app.ui.incident_inbox import incident_inbox_items, top_incidents
from app.ui.operator_status import quota_operator_summary, service_status_unavailable
from app.ui.report_lifecycle import latest_report_lifecycle, stage_by_key


REPORT_DETAIL_KEYS = {
    "quality_gate",
    "tickers",
    "candidate_whitelist",
    "auto_follow_up",
    "promoted_tickers",
}
MAX_SECONDARY_ACTIONS = 4


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


def _required_follow_up_count(follow_up_plan: dict | None) -> int:
    plan = _dict_value(follow_up_plan)
    summary = _dict_value(plan.get("summary"))
    selected = _dict_value(summary.get("selected"))
    if "required_count" in selected:
        return _int_value(selected.get("required_count"))
    return _int_value(summary.get("required_count"))


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


def _optimization_local_defaults_action(service_snapshot: dict | None) -> dict[str, Any]:
    snapshot = _dict_value(service_snapshot)
    progress = _dict_value(snapshot.get("optimization_progress"))
    primary_action = _dict_value(progress.get("primary_next_action"))
    local_projection = _dict_value(progress.get("local_resolution_projection"))
    if primary_action.get("capability") != "auto_local_defaults":
        return {}
    local_count = _int_value(
        progress.get("local_resolvable_gap_count")
        or local_projection.get("local_resolvable_gap_count")
    )
    if local_count <= 0:
        return {}
    remaining_optional = _int_value(
        progress.get("effective_optional_gap_count_after_available_local_defaults")
        if progress.get("effective_optional_gap_count_after_available_local_defaults") is not None
        else local_projection.get("projected_optional_gap_count")
    )
    command = _text(
        progress.get("local_defaults_verify_command")
        or local_projection.get("local_defaults_verify_command")
        or primary_action.get("verify_command")
    )
    detail = f"可用本機 defaults 驗證 {local_count} 項外部選配"
    if remaining_optional:
        detail += f"，驗證後剩餘 {remaining_optional} 項外部/付費選配。"
    else:
        detail += "，驗證後沒有剩餘 blocking 缺口。"
    if command:
        detail += " 維護頁已整理對應操作與驗證指令。"
    return {
        "title": "驗證本機 defaults",
        "detail": detail,
        "state": "ready",
        "route_hint": "settings:maintenance:local_defaults",
        "action_label": "查看本機操作",
        "source_ids": ["optimization:auto_local_defaults"],
    }


def _optimization_free_validation_action(service_snapshot: dict | None) -> dict[str, Any]:
    snapshot = _dict_value(service_snapshot)
    progress = _dict_value(snapshot.get("optimization_progress"))
    for action in _optimization_actions(progress):
        if not action.get("free_validation_available"):
            continue
        commands = action.get("free_validation_commands")
        command_count = len(commands) if isinstance(commands, list) else 0
        validation_label = _text(
            action.get("free_validation_label"),
            default="可用本機樣本驗證",
        )
        capability = _text(action.get("capability"))
        label = _text(action.get("label") or capability, default="外部 API")
        if capability == "company_filing_structured_api_fallback":
            detail = (
                f"{validation_label}；正式串 TEJ 或付費資料商前，"
                f"先用 {command_count or 1} 組免費檢查驗證 JSON/HTTP 格式。"
            )
            return {
                "title": "驗證公司文件 API 格式",
                "detail": detail,
                "state": "attention",
                "route_hint": "settings:maintenance:structured_api",
                "action_label": "查看免費驗證",
                "source_ids": ["optimization:company_filing_structured_api_fallback"],
            }
        return {
            "title": f"驗證{label}",
            "detail": f"{validation_label}；正式啟用外部服務前先跑免費驗證。",
            "state": "attention",
            "route_hint": "settings:maintenance",
            "action_label": "查看免費驗證",
            "source_ids": [f"optimization:{capability}" if capability else "optimization"],
        }
    return {}


def _optimization_actions(progress: dict) -> list[dict]:
    actions: list[dict] = []
    primary_action = _dict_value(progress.get("primary_next_action"))
    if primary_action:
        actions.append(primary_action)
    for action in progress.get("prioritized_next_actions") or progress.get("next_actions") or []:
        if isinstance(action, dict):
            actions.append(action)
    deduped: list[dict] = []
    seen: set[str] = set()
    for action in actions:
        capability = _text(action.get("capability"))
        key = capability or _text(action.get("label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _healthy_read_reason(*, quota_missing: bool) -> str:
    reason = "背景任務、品質門檻與必補資料缺口都沒有阻塞。"
    if quota_missing:
        return f"{reason}模型額度狀態暫不可讀，但不影響閱讀既有報告。"
    return reason


def _healthy_read_risk(*, quota_missing: bool) -> str:
    if quota_missing:
        return "閱讀現有報告不消耗額度；送出新分析或重跑前再確認 AI 額度。"
    return "仍需把報告視為研究輔助，不是買賣指令。"


def _retryable_failure_affecting_report(task_summary: dict | None, report_id: Any) -> dict:
    if report_id is None:
        return {}
    report_id_text = str(report_id).strip()
    for failure in _task_summary_failures(task_summary):
        if not failure.get("retryable"):
            continue
        if str(failure.get("report_id") or "").strip() == report_id_text:
            return failure
    return {}


def _task_summary_failures(task_summary: dict | None) -> list[dict]:
    if not isinstance(task_summary, dict):
        return []
    failures = [row for row in task_summary.get("recent_failures") or [] if isinstance(row, dict)]
    seen = {_task_failure_identity(row) for row in failures}
    for row in task_summary.get("recent") or []:
        if not isinstance(row, dict) or not _task_row_failed(row):
            continue
        identity = _task_failure_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        failures.append(row)
    return failures


def _task_row_failed(row: dict) -> bool:
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return bool(
        status in {"failed", "failure", "cancelled", "error"}
        or celery_status in {"failed", "failure", "revoked"}
        or row.get("error")
        or row.get("error_category")
    )


def _latest_task_successful(task_summary: dict | None) -> bool:
    return _task_row_successful(_latest_task_row(task_summary))


def _latest_task_running(task_summary: dict | None) -> dict:
    task = _latest_task_row(task_summary)
    return task if _task_row_running(task) else {}


def _latest_task_row(task_summary: dict | None) -> dict:
    if not isinstance(task_summary, dict):
        return {}
    for key in ("latest", "latest_task"):
        row = task_summary.get(key)
        if isinstance(row, dict):
            return row
    recent = task_summary.get("recent")
    if isinstance(recent, list):
        for row in recent:
            if isinstance(row, dict):
                return row
    return {}


def _task_row_successful(row: dict) -> bool:
    if row.get("successful") is True:
        return True
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return status in {"success", "successful", "succeeded", "completed", "done"} or (
        celery_status in {"success", "successful", "succeeded"}
    )


def _task_row_running(row: dict) -> bool:
    if _task_row_successful(row) or _task_row_failed(row):
        return False
    if row.get("running") is True:
        return True
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
        "in_progress",
        "processing",
        "submitted",
        "scheduled",
    } or celery_status in {
        "pending",
        "queued",
        "received",
        "retry",
        "running",
        "started",
    }


def _task_failure_identity(row: dict) -> str:
    for key in ("task_id", "id"):
        value = _text(row.get(key))
        if value:
            return f"{key}:{value}"
    return ":".join(
        [
            _text(row.get("operation"), default="task"),
            _text(row.get("error_category"), default="unknown"),
            _text(row.get("finished_at") or row.get("created_at")),
        ]
    )


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


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
