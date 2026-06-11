from __future__ import annotations

from typing import Any

from app.ui.data_gap_actions import data_gap_action_items
from app.ui.operator_task_state import task_summary_failures


REPORT_DETAIL_KEYS = {
    "quality_gate",
    "tickers",
    "candidate_whitelist",
    "auto_follow_up",
    "promoted_tickers",
}


def operator_action(
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


def primary_data_gap_action(report_payload: dict, follow_up_plan: dict | None) -> dict:
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


def required_follow_up_count(follow_up_plan: dict | None) -> int:
    plan = dict_value(follow_up_plan)
    summary = dict_value(plan.get("summary"))
    selected = dict_value(summary.get("selected"))
    if "required_count" in selected:
        return int_value(selected.get("required_count"))
    return int_value(summary.get("required_count"))


def data_gap_action_impact(action: dict) -> str:
    impact = text_value(action.get("impact"), default="補強最新版報告資料缺口。")
    post_action_hint = text_value(action.get("post_action_hint"))
    if post_action_hint and post_action_hint not in impact:
        return f"{impact}；{post_action_hint}"
    return impact


def data_gap_action_source_ids(action: dict, report_id_value: Any) -> list[Any]:
    source_ids: list[Any] = []
    if report_id_value is not None:
        source_ids.append(f"report:{report_id_value}")
    source_ids.extend(action.get("tickers") or [])
    return source_ids


def healthy_read_reason(*, quota_missing: bool) -> str:
    reason = "背景任務、品質門檻與必補資料缺口都沒有阻塞。"
    if quota_missing:
        return f"{reason}模型額度狀態暫不可讀，但不影響閱讀既有報告。"
    return reason


def healthy_read_risk(*, quota_missing: bool) -> str:
    if quota_missing:
        return "閱讀現有報告不消耗額度；送出新分析或重跑前再確認 AI 額度。"
    return "仍需把報告視為研究輔助，不是買賣指令。"


def retryable_failure_affecting_report(
    task_summary: dict | None, report_id_value: Any
) -> dict:
    if report_id_value is None:
        return {}
    report_id_text = str(report_id_value).strip()
    for failure in task_summary_failures(task_summary):
        if not failure.get("retryable"):
            continue
        if str(failure.get("report_id") or "").strip() == report_id_text:
            return failure
    return {}


def latest_report(reports: list[dict] | None) -> dict:
    if not isinstance(reports, list):
        return {}
    for report in reports:
        if isinstance(report, dict):
            return report
    return {}


def has_report_detail_payload(report: dict) -> bool:
    return bool(report) and any(key in report for key in REPORT_DETAIL_KEYS)


def report_id(report_payload: dict, latest_report_payload: dict) -> Any:
    for report in (report_payload, latest_report_payload):
        if not isinstance(report, dict):
            continue
        for key in ("report_id", "id"):
            if report.get(key) is not None:
                return report[key]
    return None


def dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def text_value(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
