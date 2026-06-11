from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.ui.operator_status import quota_operator_summary


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
CATEGORY_ORDER = {
    "task_queue": 0,
    "report_quality": 1,
    "whitelist": 2,
    "data_source": 3,
    "vector_store": 4,
    "runtime_storage": 5,
    "quota": 6,
    "external_config": 7,
    "visual_rag": 8,
    "timeout": 9,
    "cancelled": 10,
    "unknown": 11,
}
FAILURE_CATEGORY_MAP = {
    "payload_validation": "whitelist",
    "data_source": "data_source",
    "vector_store": "vector_store",
    "runtime_storage": "runtime_storage",
}
ALLOWED_RAW_FAILURE_CATEGORIES = {
    "quota",
    "task_queue",
    "visual_rag",
    "external_config",
    "timeout",
    "cancelled",
}


def incident_inbox_items(
    service_snapshot: dict | None,
    task_summary: dict | None,
    quota: dict | None = None,
    report_lifecycle: dict | None = None,
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    service = _dict_value(service_snapshot)
    summary = _dict_value(task_summary)
    task_queue = _dict_value(service.get("task_queue"))
    totals = _dict_value(summary.get("totals"))
    latest_success_timestamp = _latest_success_timestamp(summary)

    if not _queue_ready(task_queue):
        incidents.append(
            {
                "id": "task_queue_unavailable",
                "severity": "critical",
                "category": "task_queue",
                "title": "背景任務未就緒",
                "impact": "分析、補強與資料刷新可能無法完成。",
                "next_action": "到維護頁檢查 Redis/Celery worker。",
                "action_label": "查看維護",
                "route_hint": "settings:maintenance",
                "retryable": False,
                "source": "task_queue",
                "created_at": "",
                "dedupe_key": "task_queue:unavailable",
            }
        )

    stale_count = _int_value(totals.get("stale_running_count"))
    if stale_count > 0:
        incidents.append(
            {
                "id": "task_queue_stale_running",
                "severity": "critical",
                "category": "task_queue",
                "title": f"有 {stale_count} 個任務疑似卡住",
                "impact": "新的補強或報告任務可能排隊等待過久。",
                "next_action": "到維護頁查看任務狀態並重試可重試任務。",
                "action_label": "查看任務",
                "route_hint": "settings:maintenance",
                "retryable": False,
                "source": "task_queue",
                "created_at": "",
                "dedupe_key": "task_queue:stale_running",
            }
        )

    incidents.extend(
        _task_alert_incidents(
            summary,
            latest_success_timestamp=latest_success_timestamp,
        )
    )
    incidents.extend(
        _failure_incidents(
            summary,
            latest_success_timestamp=latest_success_timestamp,
        )
    )
    quota_incident = _quota_incident(_dict_value(quota))
    if quota_incident:
        incidents.append(quota_incident)
    lifecycle_incident = _report_lifecycle_incident(_dict_value(report_lifecycle))
    if lifecycle_incident:
        incidents.append(lifecycle_incident)

    return top_incidents(_dedupe_incidents(incidents), limit=50)


def top_incidents(incidents: list[dict], limit: int = 3) -> list[dict]:
    return sorted(incidents, key=_incident_sort_key)[:limit]


def incident_counts(incidents: list[dict]) -> dict[str, int]:
    return {
        "critical": sum(1 for incident in incidents if incident.get("severity") == "critical"),
        "warning": sum(1 for incident in incidents if incident.get("severity") == "warning"),
        "info": sum(1 for incident in incidents if incident.get("severity") == "info"),
    }


def _task_alert_incidents(
    task_summary: dict,
    *,
    latest_success_timestamp: float = 0.0,
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for index, alert in enumerate(_list_value(task_summary.get("alerts"))):
        severity = "critical" if alert.get("severity") == "error" else "warning"
        code = _text(alert.get("code"), default=f"alert_{index}")
        message = _text(alert.get("message"), default=code)
        category = _task_alert_category(alert)
        dedupe_key = (
            "task_queue:stale_running"
            if _is_stale_running_alert(alert)
            else f"task_alert:{category}:{code}"
        )
        next_steps_value = alert.get("next_steps")
        next_steps = (
            [str(step).strip() for step in next_steps_value if str(step).strip()]
            if isinstance(next_steps_value, list)
            else []
        )
        incident = {
            "id": f"task_alert_{code}",
            "severity": severity,
            "category": category,
            "title": message,
            "impact": "背景任務觀測已回報異常。",
            "next_action": "；".join(next_steps) if next_steps else "到維護頁查看背景任務觀測。",
            "action_label": "查看維護",
            "route_hint": "settings:maintenance",
            "retryable": False,
            "source": code,
            "created_at": "",
            "dedupe_key": dedupe_key,
        }
        if latest_success_timestamp > 0 and not _is_stale_running_alert(alert):
            incident["trend_only"] = True
        incidents.append(incident)
    return incidents


def _task_alert_category(alert: dict) -> str:
    if _is_stale_running_alert(alert):
        return "task_queue"
    if _text(alert.get("error_category")):
        return _failure_category(alert)
    return "task_queue"


def _is_stale_running_alert(alert: dict) -> bool:
    code = _text(alert.get("code")).casefold().replace("-", "_")
    message = _text(alert.get("message")).casefold().replace("-", " ")
    return "stale_running" in code or "stale running" in message or "疑似卡住" in message


def _failure_incidents(
    task_summary: dict,
    *,
    latest_success_timestamp: float = 0.0,
) -> list[dict[str, Any]]:
    incidents = []
    for failure in _recent_failures(task_summary):
        category = _failure_category(failure)
        identity = _failure_identity(failure)
        task_id = _text(failure.get("task_id"))
        operation = _text(failure.get("operation"), default="task")
        retryable = bool(failure.get("retryable"))
        incident = {
            "id": f"failure_{identity.replace(':', '_')}_{category}",
            "severity": _failure_severity(failure, category),
            "category": category,
            "title": _text(failure.get("error_summary"), default=_failure_title(category)),
            "impact": _failure_impact(category),
            "next_action": _text(
                failure.get("next_action"),
                default=_failure_next_action(category, retryable),
            ),
            "action_label": _failure_action_label(category, retryable),
            "route_hint": f"task:{task_id}" if task_id else "settings:maintenance",
            "retryable": retryable,
            "source": _failure_source(failure, operation),
            "created_at": _text(failure.get("finished_at") or failure.get("created_at")),
            "dedupe_key": f"failure:{category}:{identity}",
        }
        if _is_failure_before_latest_success(failure, latest_success_timestamp):
            incident["historical_after_latest_success"] = True
        incidents.append(incident)
    return incidents


def _quota_incident(quota: dict) -> dict[str, Any] | None:
    if not quota:
        return None
    summary = quota_operator_summary(quota)
    if summary.get("state") == "ready":
        return None
    model = summary.get("recommended_model") or "-"
    return {
        "id": f"quota_{model}",
        "severity": "warning",
        "category": "quota",
        "title": "AI 額度需注意",
        "impact": f"目前建議模型 {model} 額度狀態為 {summary.get('remaining') or '-'}。",
        "next_action": "查看額度頁，等待重置或確認 fallback 模型。",
        "action_label": "查看額度",
        "route_hint": "settings:ai_quota",
        "retryable": False,
        "source": model,
        "created_at": "",
        "dedupe_key": f"quota:{model}",
    }


def _report_lifecycle_incident(lifecycle: dict) -> dict[str, Any] | None:
    state = _text(lifecycle.get("overall_state"))
    if state not in {"blocked", "attention"}:
        return None
    report_id = lifecycle.get("report_id")
    source = f"report:{report_id}" if report_id is not None else "report"
    return {
        "id": f"report_quality_{report_id or 'latest'}",
        "severity": "critical" if state == "blocked" else "warning",
        "category": "report_quality",
        "title": lifecycle.get("trust_label") or "報告品質需確認",
        "impact": lifecycle.get("trust_explanation") or "最新版報告需要人工確認。",
        "next_action": lifecycle.get("primary_action") or "查看報告中心",
        "action_label": lifecycle.get("primary_action") or "查看報告",
        "route_hint": lifecycle.get("route_hint") or "report_center",
        "retryable": False,
        "source": source,
        "created_at": "",
        "dedupe_key": f"report_quality:{source}:{state}",
    }


def _recent_failures(task_summary: dict) -> list[dict]:
    rows: list[dict] = []
    rows.extend(_list_value(task_summary.get("recent_failures")))

    for row in _list_value(task_summary.get("recent")):
        if not _is_failed_task(row):
            continue
        rows.append(row)
    return rows


def _is_failed_task(row: dict) -> bool:
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    if status in {"failed", "failure", "cancelled", "error"} or celery_status in {
        "failed",
        "failure",
        "revoked",
    }:
        return True
    return bool(row.get("error") or row.get("error_category"))


def _failure_identity(row: dict) -> str:
    task_id = _text(row.get("task_id"))
    if task_id:
        return f"task:{task_id}"
    run_id = _text(row.get("id"))
    if run_id:
        return f"run:{run_id}"
    return "row:" + ":".join(
        [
            _text(row.get("operation"), default="task"),
            _text(row.get("error_category"), default="unknown"),
            _text(row.get("finished_at") or row.get("created_at")),
        ]
    )


def _failure_category(failure: dict) -> str:
    raw_category = _text(failure.get("error_category")).casefold()
    if not raw_category:
        return "unknown"
    if raw_category in FAILURE_CATEGORY_MAP:
        return FAILURE_CATEGORY_MAP[raw_category]
    if raw_category in ALLOWED_RAW_FAILURE_CATEGORIES:
        return raw_category
    return "unknown"


def _failure_severity(failure: dict, category: str) -> str:
    raw_severity = _text(failure.get("error_severity")).casefold()
    if raw_severity in {"critical", "error"}:
        return "critical"
    if raw_severity in {"warning", "warn"}:
        return "warning"
    if raw_severity == "info":
        return "info"
    return "critical" if category == "runtime_storage" else "warning"


def _failure_source(failure: dict, operation: str) -> str:
    task_id = _text(failure.get("task_id"))
    if task_id:
        return task_id
    run_id = _text(failure.get("id"))
    if run_id:
        return f"run:{run_id}"
    return operation


def _failure_title(category: str) -> str:
    return {
        "whitelist": "白名單或輸入擋下任務",
        "data_source": "資料來源抓取失敗",
        "vector_store": "RAG 向量檢索曾降級",
        "runtime_storage": "本機儲存失敗",
        "quota": "AI 額度需注意",
        "task_queue": "背景任務失敗",
        "visual_rag": "Visual RAG 設定需確認",
        "external_config": "外部配置缺失",
        "timeout": "任務逾時",
        "cancelled": "任務已取消",
    }.get(category, "有失敗任務")


def _failure_impact(category: str) -> str:
    return {
        "whitelist": "補強或重跑沒有進入有效資料流程。",
        "data_source": "最新版報告可能缺少最新市場或公司資料。",
        "vector_store": "報告可降級完成，但檢索覆蓋率較低。",
        "runtime_storage": "報告檔案、SQLite 或備份可能沒有寫入成功。",
        "quota": "AI 模型額度或路由限制導致任務失敗。",
        "task_queue": "背景任務服務異常導致任務失敗。",
        "visual_rag": "Visual RAG 設定或文件後援導致任務失敗。",
        "external_config": "外部服務、API key 或部署設定缺失導致任務失敗。",
        "timeout": "任務執行時間過長，可能需要重試或縮小輸入範圍。",
        "cancelled": "任務已取消，需要確認是否重新送出。",
    }.get(category, "近期任務失敗，需查看維護頁。")


def _failure_next_action(category: str, retryable: bool) -> str:
    if category == "whitelist":
        return "修正輸入後重試" if retryable else "檢查輸入與白名單"
    if retryable:
        return "到維護頁重試此任務"
    return "到維護頁查看失敗診斷"


def _failure_action_label(category: str, retryable: bool) -> str:
    if retryable:
        return "重試任務"
    if category == "quota":
        return "查看額度"
    if category in {"external_config", "task_queue", "visual_rag", "data_source"}:
        return "修復配置"
    return "檢查任務"


def _latest_success_timestamp(task_summary: dict) -> float:
    candidates: list[float] = []
    for row in _candidate_task_rows(task_summary):
        if not _task_successful(row):
            continue
        timestamp = _task_event_timestamp(row)
        if timestamp > 0:
            candidates.append(timestamp)
    return max(candidates, default=0.0)


def _candidate_task_rows(task_summary: dict) -> list[dict]:
    rows: list[dict] = []
    for key in ("latest", "latest_task"):
        value = task_summary.get(key)
        if isinstance(value, dict):
            rows.append(value)
    for key in ("recent", "recent_successes"):
        rows.extend(_list_value(task_summary.get(key)))
    return rows


def _task_successful(row: dict) -> bool:
    if row.get("successful") is True:
        return True
    status = _text(row.get("status")).casefold()
    celery_status = _text(row.get("celery_status")).casefold()
    return status in {"success", "successful", "succeeded", "completed", "done"} or (
        celery_status in {"success", "successful", "succeeded"}
    )


def _is_failure_before_latest_success(failure: dict, latest_success_timestamp: float) -> bool:
    if latest_success_timestamp <= 0:
        return False
    failure_timestamp = _task_event_timestamp(failure)
    return 0 < failure_timestamp < latest_success_timestamp


def _task_event_timestamp(row: dict) -> float:
    return _created_at_timestamp(
        row.get("finished_at") or row.get("updated_at") or row.get("created_at")
    )


def _dedupe_incidents(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        key = _text(incident.get("dedupe_key"), default=_text(incident.get("id")))
        current = selected.get(key)
        if current is None or _incident_is_newer(incident, current):
            selected[key] = incident
    return list(selected.values())


def _incident_is_newer(candidate: dict, current: dict) -> bool:
    candidate_time = _created_at_timestamp(candidate.get("created_at"))
    current_time = _created_at_timestamp(current.get("created_at"))
    if candidate_time != current_time:
        return candidate_time > current_time
    return _incident_sort_key(candidate) < _incident_sort_key(current)


def _incident_sort_key(incident: dict) -> tuple[int, int, int, float, str]:
    severity = SEVERITY_ORDER.get(_text(incident.get("severity")), 9)
    category = CATEGORY_ORDER.get(_text(incident.get("category")), 9)
    retry_rank = 0 if incident.get("retryable") else 1
    created_at_rank = -_created_at_timestamp(incident.get("created_at"))
    return (severity, category, retry_rank, created_at_rank, _text(incident.get("id")))


def _created_at_timestamp(value: Any) -> float:
    text = _text(value)
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _queue_ready(task_queue: dict) -> bool:
    return bool(
        task_queue.get("ready")
        and task_queue.get("processing_ready")
        and task_queue.get("worker_online")
    )


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
