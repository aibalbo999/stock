from __future__ import annotations


EXTERNAL_CONFIG_FAILURE_CATEGORIES = {
    "data_source",
    "task_queue",
    "visual_rag",
}

TASK_FAILURE_ACTION_ROUTE_ORDER = (
    "一鍵重試",
    "外部配置缺失",
    "需人工處理",
)

TASK_FAILURE_ACTION_ROUTE_DETAILS = {
    "一鍵重試": "可由維護頁直接重試；若為額度限制，等額度恢復或切換 fallback 後再重試。",
    "外部配置缺失": "先修復 Redis/Celery、資料源 token、Visual RAG 或文件後援設定，再重送任務。",
    "需人工處理": "payload、輸入範圍或取消狀態需人工檢查，修正後從原工作流程重送。",
}


def task_failure_drilldown_rows(task_summary: dict) -> list[dict]:
    failures = _task_summary_failures(task_summary)
    return [
        {
            "run_id": row.get("id") or "-",
            "operation": row.get("operation") or "-",
            "status": row.get("status") or "-",
            "task_id": row.get("task_id") or "-",
            "category": row.get("error_category") or "-",
            "severity": row.get("error_severity") or "-",
            "summary": row.get("error_summary") or "-",
            "retry": "可重試" if row.get("retryable") else "需人工",
            "retry_kind": row.get("retry_kind") or "-",
            "action_route": task_failure_action_route(row),
            "action_route_detail": task_failure_action_route_detail(row),
            "next_action": row.get("next_action") or _fallback_failure_next_action(row),
            "next_steps": _task_next_steps_text(row),
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


def task_failure_action_route(row: dict) -> str:
    if _is_external_config_failure(row):
        return "外部配置缺失"
    if row.get("retryable"):
        return "一鍵重試"
    return "需人工處理"


def task_failure_action_route_detail(row: dict) -> str:
    return TASK_FAILURE_ACTION_ROUTE_DETAILS.get(task_failure_action_route(row), "-")


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
    operation = str(row.get("operation") or "unknown")
    run_id = row.get("id") or "-"
    return f"{operation}｜run #{run_id}｜{task_id}"


def _is_external_config_failure(row: dict) -> bool:
    category = str(row.get("error_category") or "").strip()
    if category in EXTERNAL_CONFIG_FAILURE_CATEGORIES:
        return True
    next_steps_text = _task_next_steps_text(row)
    return any(
        marker in next_steps_text
        for marker in (
            "/services/status",
            "Redis",
            "Celery",
            "資料源 token",
            "Visual RAG",
            "company filing 後援設定",
        )
    )


def _task_failure_route_example(row: dict) -> str:
    operation = str(row.get("operation") or "unknown")
    task_id = str(row.get("task_id") or "").strip()
    run_id = row.get("id")
    if task_id:
        return f"{operation}｜{task_id}"
    if run_id:
        return f"{operation}｜run #{run_id}"
    return operation


def _fallback_failure_next_action(row: dict) -> str:
    if row.get("task_id"):
        return "查看任務狀態，確認 payload 是否支援自動重試。"
    return "缺少 task id；請從 run 明細檢查。"


def _task_next_steps_text(row: dict) -> str:
    next_steps = row.get("next_steps")
    if not isinstance(next_steps, list):
        return "-"
    steps = [str(step).strip() for step in next_steps if str(step).strip()]
    return "；".join(steps) if steps else "-"
