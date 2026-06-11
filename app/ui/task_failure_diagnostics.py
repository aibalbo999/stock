from __future__ import annotations

from app.ui.task_failure_catalog import (
    TASK_FAILURE_ACTION_ROUTE_DETAILS,
    TASK_FAILURE_ACTION_ROUTE_ORDER,
    task_failure_action_route,
    task_failure_action_route_detail,
    task_failure_category_label,
    task_failure_operation_label,
    task_failure_raw_next_steps_text,
    task_failure_retry_kind_label,
    task_failure_severity_label,
)


def task_failure_drilldown_rows(task_summary: dict) -> list[dict]:
    failures = _task_summary_failures(task_summary)
    return [
        {
            "run_id": row.get("id") or "-",
            "operation": task_failure_operation_label(row.get("operation")),
            "status": row.get("status") or "-",
            "task_id": row.get("task_id") or "-",
            "category": task_failure_category_label(row.get("error_category")),
            "severity": task_failure_severity_label(row.get("error_severity")),
            "summary": task_failure_summary_text(row),
            "retry": "可重試" if row.get("retryable") else "需人工",
            "retry_kind": task_failure_retry_kind_label(row.get("retry_kind")),
            "action_route": task_failure_action_route(row),
            "action_route_detail": task_failure_action_route_detail(row),
            "next_action": task_failure_next_action_text(row),
            "next_steps": task_failure_next_steps_text(row),
            "error": row.get("error") or "-",
            "started_at": row.get("started_at") or "-",
        }
        for row in failures
    ]


def task_retry_options(task_summary: dict) -> list[dict]:
    options = []
    for row in _task_summary_failures(task_summary):
        task_id = str(row.get("task_id") or "").strip()
        if not task_id or not row.get("retryable"):
            continue
        options.append(
            {
                "task_id": task_id,
                "label": _task_retry_option_label(row),
                "operation": row.get("operation") or "unknown",
                "run_id": row.get("id"),
                "retry_endpoint": row.get("retry_endpoint") or f"POST /tasks/{task_id}/retry",
                "action_route": task_failure_action_route(row),
                "action_route_detail": task_failure_action_route_detail(row),
                "retry_guarded": task_failure_retry_guarded(row),
                "retry_guard_message": task_failure_retry_guard_message(row),
            }
        )
    return options


def recommended_task_retry_option(
    retry_options: list[dict],
    *,
    preferred_task_id: str | None = None,
) -> dict:
    safe_options = [option for option in retry_options if not option.get("retry_guarded")]
    preferred = str(preferred_task_id or "").strip()
    if preferred:
        for option in safe_options:
            if str(option.get("task_id") or "").strip() == preferred:
                return option
    return safe_options[0] if safe_options else {}


def task_retry_option_index(
    retry_options: list[dict],
    *,
    preferred_task_id: str | None = None,
) -> int:
    preferred = str(preferred_task_id or "").strip()
    if not preferred:
        return 0
    for index, option in enumerate(retry_options):
        if str(option.get("task_id") or "").strip() == preferred:
            return index
    return 0


def task_failure_action_route_rows(task_summary: dict) -> list[dict]:
    grouped = {route: {"count": 0, "examples": []} for route in TASK_FAILURE_ACTION_ROUTE_ORDER}
    for row in _task_summary_failures(task_summary):
        route = task_failure_action_route(row)
        group = grouped.setdefault(route, {"count": 0, "examples": []})
        group["count"] += 1
        example = _task_failure_route_example(row)
        if example and len(group["examples"]) < 3:
            group["examples"].append(example)
    return [
        {
            "處理路徑": route,
            "數量": group["count"],
            "說明": TASK_FAILURE_ACTION_ROUTE_DETAILS.get(route, "-"),
            "代表任務": "；".join(group["examples"]) if group["examples"] else "-",
        }
        for route, group in grouped.items()
        if group["count"]
    ]


def task_operation_summary_rows(task_summary: dict) -> list[dict]:
    rows = task_summary.get("by_operation") if isinstance(task_summary, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        {
            "任務類型": task_failure_operation_label(row.get("operation")),
            "數量": int(row.get("count") or 0),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def task_failure_category_summary_rows(task_summary: dict) -> list[dict]:
    rows = task_summary.get("by_error_category") if isinstance(task_summary, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        {
            "失敗分類": task_failure_category_label(row.get("error_category")),
            "嚴重度": task_failure_severity_label(
                row.get("severity") or row.get("error_severity")
            ),
            "數量": int(row.get("count") or 0),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def task_failure_category_daily_rows(task_summary: dict) -> list[dict]:
    rows = task_summary.get("error_category_daily") if isinstance(task_summary, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        {
            "日期": row.get("date") or "-",
            "失敗分類": task_failure_category_label(row.get("error_category")),
            "嚴重度": task_failure_severity_label(
                row.get("severity") or row.get("error_severity")
            ),
            "數量": int(row.get("count") or 0),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def task_summary_alert_rows(task_summary: dict) -> list[dict]:
    alerts = task_summary.get("alerts") if isinstance(task_summary, dict) else None
    if not isinstance(alerts, list):
        return []
    return [
        {
            "severity": _task_alert_severity(alert),
            "severity_label": task_failure_severity_label(alert.get("severity")),
            "message": task_summary_alert_message(alert),
            "next_steps": task_summary_alert_next_steps(alert),
        }
        for alert in alerts
        if isinstance(alert, dict)
    ]


def task_failure_summary_text(row: dict) -> str:
    return _operator_alert_text(row.get("error_summary") or "-")


def task_failure_next_steps_text(row: dict) -> str:
    category = str(row.get("error_category") or "").strip()
    if category == "task_queue":
        return (
            "到系統設定 > 維護 > 背景任務觀測確認背景任務佇列與背景執行器。；"
            "修復後重新送出任務。"
        )
    return task_failure_raw_next_steps_text(row)


def task_failure_next_action_text(row: dict) -> str:
    next_action = str(row.get("next_action") or "").strip()
    if next_action and not _has_raw_task_action_endpoint(next_action):
        return _operator_alert_text(next_action)
    if next_action:
        return task_failure_action_route_detail(row)
    return _fallback_failure_next_action(row)


def task_summary_alert_message(alert: dict) -> str:
    category = str(alert.get("error_category") or "").strip()
    message = str(alert.get("message") or "").strip()
    count = int(alert.get("count") or 0)
    if _has_raw_operator_diagnostics(message):
        if not category:
            return _operator_alert_text(message)
        label = task_failure_category_label(category or "unknown")
        count_text = f"近期出現 {count} 次" if count else "需要處理"
        return f"{label}{count_text}，請先依下方步驟處理。"
    if message:
        return _operator_alert_text(message)
    code = str(alert.get("code") or "").strip()
    if code:
        return _operator_alert_text(code.replace("_", " "))
    return "背景任務需要檢查，請先查看下方處理步驟。"


def task_summary_alert_next_steps(alert: dict) -> str:
    category = str(alert.get("error_category") or "").strip()
    if category:
        return task_failure_next_steps_text(alert)
    next_steps = task_failure_raw_next_steps_text(alert)
    return _operator_alert_text(next_steps) if next_steps != "-" else "-"


def task_failure_retry_guarded(row: dict) -> bool:
    return bool(row.get("retryable") and task_failure_action_route(row) != "一鍵重試")


def task_failure_retry_guard_message(row: dict) -> str:
    if not task_failure_retry_guarded(row):
        return ""
    return f"先修配置再重試：{task_failure_action_route_detail(row)}"


def _task_summary_failures(task_summary: dict) -> list[dict]:
    if not isinstance(task_summary, dict):
        return []
    failures = task_summary.get("recent_failures")
    if not isinstance(failures, list):
        return []
    return [row for row in failures if isinstance(row, dict)]


def _task_retry_option_label(row: dict) -> str:
    task_id = str(row.get("task_id") or "")
    operation = task_failure_operation_label(row.get("operation") or "unknown")
    run_id = row.get("id") or "-"
    return f"{operation}｜run #{run_id}｜{task_id}"


def _task_failure_route_example(row: dict) -> str:
    operation = task_failure_operation_label(row.get("operation") or "unknown")
    task_id = str(row.get("task_id") or "").strip()
    run_id = row.get("id")
    if task_id:
        return f"{operation}｜{task_id}"
    if run_id:
        return f"{operation}｜run #{run_id}"
    return operation


def _fallback_failure_next_action(row: dict) -> str:
    if row.get("task_id"):
        return "查看任務狀態，確認任務輸入是否支援自動重試。"
    return "缺少任務編號；請從 run 明細檢查。"


def _has_raw_task_action_endpoint(text: str) -> bool:
    return "POST " in text or "/tasks/" in text


def _task_alert_severity(alert: dict) -> str:
    severity = str(alert.get("severity") or "info").strip().casefold()
    if severity in {"error", "warning", "success", "info"}:
        return severity
    if severity == "warn":
        return "warning"
    return "info"


def _has_raw_operator_diagnostics(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "/services/status",
            "task_queue.",
            "worker_online",
            "processing_ready",
            "broker_ok",
            "backend_ok",
            "submission_contract_ready",
        )
    )


def _operator_alert_text(text: str) -> str:
    replacements = {
        "Redis/Celery queue 或 worker": "背景任務佇列或背景執行器",
        "Redis/Celery worker": "背景執行器",
        "Redis/Celery": "背景任務服務",
        "/services/status": "系統設定 > 維護 > 背景任務觀測",
        "task_queue.ready": "背景任務提交狀態",
        "payload_validation": "輸入驗證",
        "payload ": "任務輸入",
        "payload": "任務輸入",
        "processing_ready": "背景任務執行狀態",
        "worker_online": "背景執行器是否在線",
        "worker": "背景執行器",
        "broker_ok": "Redis 訊息佇列連線",
        "backend_ok": "Redis 結果儲存連線",
        "submission_contract_ready": "背景任務送出契約",
    }
    result = str(text or "").strip()
    for raw, label in replacements.items():
        result = result.replace(raw, label)
    result = result.replace("背景任務佇列或背景執行器 異常", "背景任務佇列或背景執行器異常")
    return result
