from __future__ import annotations

from typing import Any

from app.ui.data_gap_actions import data_gap_action_items


RUNNING_STATUSES = {"queued", "started", "running", "pending", "processing"}
BLOCKED_STATUSES = {"blocked", "failed", "error"}


def latest_report_health_summary(
    report_result: dict, follow_up_plan: dict | None = None
) -> dict[str, str]:
    follow_up_plan = follow_up_plan or {}
    report_id = report_result.get("report_id") or report_result.get("id")
    topic = _text(report_result.get("topic"))
    title = _report_title(report_result, topic)
    generated_at = _format_generated_at(report_result.get("generated_at"))
    quality_gate = _dict_value(report_result.get("quality_gate"))
    quality_gate_known = _quality_gate_known(quality_gate)
    metrics = _dict_value(quality_gate.get("metrics"))
    candidates = report_result.get("candidate_whitelist") or []
    promoted_count = (
        _promoted_count(metrics, report_result) if quality_gate_known else 0
    )
    candidate_count = len([item for item in candidates if isinstance(item, dict)])
    required_count = _required_follow_up_count(follow_up_plan)
    if not report_id:
        return {
            "state": "attention",
            "quality_label": "-",
            "report_label": "尚未選擇報告",
            "report_meta_label": "尚無報告時間",
            "candidate_label": "候選 0｜正式 0",
            "follow_up_state": "missing",
            "follow_up_label": "尚無狀態",
            "action_label": "建立分析",
        }
    if not quality_gate_known:
        return {
            "state": "attention",
            "quality_label": "尚無法判斷",
            "report_label": title,
            "report_meta_label": _report_meta_label(report_id, topic, generated_at),
            "candidate_label": f"候選 {candidate_count}｜正式 {promoted_count}",
            "follow_up_state": "quality_unknown",
            "follow_up_label": "品質待確認",
            "action_label": "確認品質",
        }
    state, follow_up_state, follow_up_label, action_label = _follow_up_health_state(
        report_result,
        follow_up_plan,
        required_count,
    )
    return {
        "state": state,
        "quality_label": str(quality_gate.get("status") or "-"),
        "report_label": title,
        "report_meta_label": _report_meta_label(report_id, topic, generated_at),
        "candidate_label": f"候選 {candidate_count}｜正式 {promoted_count}",
        "follow_up_state": follow_up_state,
        "follow_up_label": follow_up_label,
        "action_label": action_label,
    }


def _report_title(report_result: dict, topic: str) -> str:
    nested_report = _dict_value(report_result.get("report"))
    return (
        _text(report_result.get("title"))
        or _text(nested_report.get("title"))
        or topic
        or "未命名報告"
    )


def _report_meta_label(report_id: object, topic: str, generated_at: str) -> str:
    parts = [f"#{report_id}", topic or "未命名主題", generated_at or "時間未標示"]
    return "｜".join(parts)


def _format_generated_at(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    return text.replace("T", " ")[:16]


def _required_follow_up_count(follow_up_plan: dict) -> int:
    summary = _dict_value(follow_up_plan.get("summary"))
    selected = _dict_value(summary.get("selected"))
    value = selected.get("required_count", summary.get("required_count", 0))
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _follow_up_health_state(
    report_result: dict,
    follow_up_plan: dict,
    required_count: int,
) -> tuple[str, str, str, str]:
    follow_up_status = _follow_up_status(report_result, follow_up_plan)
    if follow_up_status in RUNNING_STATUSES:
        return "attention", "rerun_running", "重跑中", "查看進度"
    if _follow_up_is_blocked(report_result, follow_up_plan, follow_up_status):
        return "blocked", "blocked", "補強受阻", "查看阻塞"
    if required_count > 0:
        return (
            "attention",
            "needs_data",
            f"需補強 {required_count} 項",
            _primary_data_gap_action_label(report_result, follow_up_plan),
        )
    if _has_incomplete_rerun_report(report_result):
        return "attention", "needs_retry", "重跑未完成", "重新重跑"
    return "ready", "ready", "可閱讀", "閱讀最新版"


def _primary_data_gap_action_label(report_result: dict, follow_up_plan: dict) -> str:
    items = data_gap_action_items(report_result, follow_up_plan)
    for item in items:
        if item.get("purpose") == "required" and item.get("operation") != "report_follow_up":
            return _text(item.get("action_label")) or "補強資料"
    for item in items:
        if item.get("purpose") == "required":
            return _text(item.get("action_label")) or "補強資料"
    return "補強資料"


def _follow_up_status(report_result: dict, follow_up_plan: dict) -> str:
    plan_status = _text(follow_up_plan.get("status")).casefold()
    if plan_status:
        return plan_status
    auto_follow_up = _dict_value(report_result.get("auto_follow_up"))
    return _text(auto_follow_up.get("status")).casefold()


def _follow_up_is_blocked(report_result: dict, follow_up_plan: dict, status: str) -> bool:
    if status in BLOCKED_STATUSES:
        return True
    summary = _dict_value(follow_up_plan.get("summary"))
    execution_summary = _dict_value(follow_up_plan.get("execution_summary"))
    if any(
        _boolish(value)
        for value in (
            follow_up_plan.get("rerun_blocked"),
            summary.get("rerun_blocked"),
            execution_summary.get("rerun_blocked"),
        )
    ):
        return True
    if any(
        _has_items(value)
        for value in (
            follow_up_plan.get("blockers"),
            follow_up_plan.get("rerun_blockers"),
            summary.get("rerun_blockers"),
            execution_summary.get("rerun_blockers"),
        )
    ):
        return True
    rerun_report = _rerun_report(report_result)
    rerun_status = _text(rerun_report.get("status")).casefold()
    return rerun_status in {"blocked", "failed", "error", "skipped"} and _has_items(
        rerun_report.get("blockers")
    )


def _has_incomplete_rerun_report(report_result: dict) -> bool:
    rerun_report = _rerun_report(report_result)
    return bool(rerun_report) and not bool(rerun_report.get("report_id"))


def _rerun_report(report_result: dict) -> dict:
    auto_follow_up = _dict_value(report_result.get("auto_follow_up"))
    return _dict_value(auto_follow_up.get("rerun_report"))


def _promoted_count(metrics: dict, report_result: dict) -> int:
    value = metrics.get("promoted_count")
    if value in {None, ""}:
        value = len(report_result.get("tickers") or [])
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _has_items(value: Any) -> bool:
    return isinstance(value, list | tuple | set) and bool(value)


def _boolish(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return bool(value)


def _quality_gate_known(quality_gate: dict) -> bool:
    return bool(quality_gate) and bool(_text(quality_gate.get("status")))


def _text(value: Any) -> str:
    return str(value or "").strip()
