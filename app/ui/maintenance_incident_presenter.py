from __future__ import annotations

from collections.abc import Iterable

from app.ui.incident_inbox import incident_counts, top_incidents
from app.ui.maintenance_incident_view import (
    incident_action_controls_intro_html as _incident_action_controls_intro_html,
    incident_card_html as _incident_card_html,
    incident_empty_card_html,
    incident_inbox_header_html as _incident_inbox_header_html,
    incident_list_html as _incident_list_html,
    incident_priority_summary_html as _incident_priority_summary_html,
)
from app.ui.operator_routes import operator_route_target


def incident_inbox_header_html(incidents: list[dict]) -> str:
    return _incident_inbox_header_html(incident_inbox_header_badges(incidents))


def incident_list_html(incidents: list[dict]) -> str:
    incident_html = "\n".join(incident_card_html(incident) for incident in incident_summary_cards(incidents))
    if not incident_html:
        incident_html = incident_empty_card_html()
    return _incident_list_html(incident_html)


def incident_priority_summary_html(summary: dict[str, object]) -> str:
    return _incident_priority_summary_html(summary)


def incident_action_controls_intro_html() -> str:
    return _incident_action_controls_intro_html()


def incident_inbox_header_badges(incidents: list[dict]) -> list[str]:
    counts = incident_counts(incidents)
    historical_count = sum(1 for incident in incidents if _historical_incident(incident))
    if not historical_count:
        return [
            f'Critical {counts["critical"]}',
            f'Warning {counts["warning"]}',
            f'Info {counts["info"]}',
        ]
    current_critical = sum(
        1
        for incident in incidents
        if incident.get("severity") == "critical" and not _historical_incident(incident)
    )
    current_warning = sum(
        1
        for incident in incidents
        if incident.get("severity") == "warning" and not _historical_incident(incident)
    )
    return [
        f"當前 Critical {current_critical}",
        f"當前 Warning {current_warning}",
        f"歷史/趨勢 {historical_count}",
    ]


def incident_action_priority_summary(incidents: list[dict]) -> dict[str, object]:
    counts = incident_counts(incidents)
    critical = counts["critical"]
    warning = counts["warning"]
    info = counts["info"]
    historical_count = sum(1 for incident in incidents if _historical_incident(incident))
    historical_critical = sum(
        1
        for incident in incidents
        if incident.get("severity") == "critical" and _historical_incident(incident)
    )
    current_critical = max(0, critical - historical_critical)
    retryable_count = sum(1 for incident in incidents if incident.get("retryable"))
    current_retryable_count = sum(
        1
        for incident in incidents
        if incident.get("retryable") and not _historical_incident(incident)
    )
    task_linked_count = sum(
        1
        for incident in incidents
        if str(incident.get("route_hint") or "").strip().startswith("task:")
    )
    current_task_linked_count = sum(
        1
        for incident in incidents
        if str(incident.get("route_hint") or "").strip().startswith("task:")
        and not _historical_incident(incident)
    )
    routed_count = sum(1 for incident in incidents if str(incident.get("route_hint") or "").strip())
    passive_count = max(0, len(incidents) - routed_count)
    observation_count = max(passive_count, historical_count)
    counts_label = f"Critical {critical} / Warning {warning} / Info {info}"
    if historical_count:
        counts_label = f"{counts_label}（其中 {historical_count} 個為歷史/趨勢）"

    if not incidents:
        return {
            "state": "ready",
            "title": "目前沒有待處理事件",
            "counts_label": counts_label,
            "primary_action": "可以回到分析工作區產生最新版報告。",
            "secondary_action": "維護頁仍保留服務狀態與升級稽核供備查。",
            "retryable_count": 0,
            "task_linked_count": 0,
            "current_task_linked_count": 0,
            "passive_count": 0,
            "historical_count": 0,
            "observation_count": 0,
        }

    if critical and current_critical == 0 and historical_critical == critical:
        state = "attention"
        title = f"目前任務健康，追蹤 {critical} 個歷史 Critical 紀錄"
    elif critical:
        state = "blocked"
        title = (
            f"先處理 {current_critical} 個當前 Critical 事件"
            if historical_critical
            else f"先處理 {critical} 個 Critical 事件"
        )
    elif warning:
        state = "attention"
        title = f"先確認 {warning} 個 Warning 事件"
    else:
        state = "watch"
        title = f"追蹤 {info} 個 Info 事件"

    if critical and current_critical == 0 and historical_critical == critical:
        primary_action = "最新任務已成功；先確認是否影響最新版報告，再重試必要項目。"
    elif current_retryable_count:
        primary_action = f"{current_retryable_count} 個可重試任務可直接在下方操作；先處理最高嚴重度項目。"
    elif current_task_linked_count:
        primary_action = f"{current_task_linked_count} 個當前事件已連到任務檢視；先打開任務診斷確認原因。"
    elif critical:
        primary_action = "先依下方當前 Critical 事件處理報告品質、服務或本機儲存阻塞。"
    else:
        primary_action = "先確認下方事件是否影響最新版報告，再決定是否需要補強。"

    secondary_action = (
        f"{task_linked_count} 個任務檢視、{routed_count} 個跳轉入口，"
        f"{observation_count} 個為歷史趨勢/觀測。"
    )
    return {
        "state": state,
        "title": title,
        "counts_label": counts_label,
        "primary_action": primary_action,
        "secondary_action": secondary_action,
        "retryable_count": retryable_count,
        "task_linked_count": task_linked_count,
        "current_task_linked_count": current_task_linked_count,
        "passive_count": passive_count,
        "historical_count": historical_count,
        "observation_count": observation_count,
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


def incident_card_html(incident: dict) -> str:
    repeat_count = _incident_count_value(incident.get("repeat_count"), default=1)
    hidden_count = _incident_count_value(
        incident.get("hidden_count"),
        default=max(0, repeat_count - 1),
    )
    route_hint = str(incident.get("route_hint") or "").strip()
    route_text = incident_route_caption(route_hint)
    if hidden_count > 0:
        hidden_text = f"另有 {hidden_count} 筆同類事件"
        route_text = f"{route_text}；{hidden_text}" if route_text else hidden_text
    return _incident_card_html(incident, route_text=route_text)


def incident_route_caption(route_hint: object) -> str:
    route = str(route_hint or "").strip()
    if not route:
        return ""
    return str(operator_route_target(route).get("caption") or "").strip()


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


def _historical_incident(incident: dict) -> bool:
    return bool(incident.get("historical_after_latest_success") or incident.get("trend_only"))


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


def _incident_count_value(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)
