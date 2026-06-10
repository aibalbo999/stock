from __future__ import annotations

from typing import Any


def latest_report_health_summary(
    report_result: dict, follow_up_plan: dict | None = None
) -> dict[str, str]:
    follow_up_plan = follow_up_plan or {}
    report_id = report_result.get("report_id") or report_result.get("id")
    topic = _text(report_result.get("topic"))
    title = _report_title(report_result, topic)
    generated_at = _format_generated_at(report_result.get("generated_at"))
    quality_gate = _dict_value(report_result.get("quality_gate"))
    metrics = _dict_value(quality_gate.get("metrics"))
    candidates = report_result.get("candidate_whitelist") or []
    promoted_count = _promoted_count(metrics, report_result)
    candidate_count = len([item for item in candidates if isinstance(item, dict)])
    required_count = _required_follow_up_count(follow_up_plan)
    if not report_id:
        return {
            "state": "attention",
            "quality_label": "-",
            "report_label": "尚未選擇報告",
            "report_meta_label": "尚無報告時間",
            "candidate_label": "候選 0｜正式 0",
            "follow_up_label": "尚無狀態",
            "action_label": "建立分析",
        }
    state = "attention" if required_count else "ready"
    follow_up_label = f"需補強 {required_count} 項" if required_count else "可閱讀"
    action_label = "補強資料" if required_count else "閱讀最新版"
    return {
        "state": state,
        "quality_label": str(quality_gate.get("status") or "-"),
        "report_label": title,
        "report_meta_label": _report_meta_label(report_id, topic, generated_at),
        "candidate_label": f"候選 {candidate_count}｜正式 {promoted_count}",
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


def _text(value: Any) -> str:
    return str(value or "").strip()
