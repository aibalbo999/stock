from __future__ import annotations


EXTERNAL_CONFIG_FAILURE_CATEGORIES = {
    "data_source",
    "external_config",
    "task_queue",
    "visual_rag",
}

MANUAL_FAILURE_CATEGORIES = {
    "cancelled",
    "payload_validation",
    "runtime_storage",
    "vector_store",
}

TASK_FAILURE_ACTION_ROUTE_ORDER = (
    "一鍵重試",
    "外部配置缺失",
    "需人工處理",
)

TASK_FAILURE_ACTION_ROUTE_DETAILS = {
    "一鍵重試": "可由維護頁直接重試；若為額度限制，等額度恢復或切換 fallback 後再重試。",
    "外部配置缺失": "先修復 Redis/Celery、資料源 token、Structured API、Visual RAG 或文件後援設定，再重送任務。",
    "需人工處理": "payload、輸入範圍、向量庫/本機儲存或取消狀態需人工檢查，修正後從原工作流程重送。",
}

CATEGORY_LABELS = {
    "quota": "模型/API 額度",
    "task_queue": "背景任務服務",
    "data_source": "資料來源",
    "external_config": "外部設定",
    "payload_validation": "輸入/白名單",
    "runtime_storage": "儲存/資料庫",
    "vector_store": "向量資料庫",
    "visual_rag": "Visual RAG",
    "stale_running": "長時間執行",
    "cancelled": "已取消",
    "unknown": "未知",
}

SEVERITY_LABELS = {
    "critical": "嚴重",
    "error": "錯誤",
    "warning": "警告",
    "warn": "警告",
    "info": "資訊",
}

OPERATION_LABELS = {
    "report_generation": "報告生成",
    "data_operation": "資料補強",
    "market_refresh": "市場資料刷新",
    "company_filings_fetch": "公司文件抓取",
    "manual_ingest": "手動資料匯入",
    "rss_fetch": "RSS 抓取",
    "visual_rag": "Visual RAG",
    "after_close_report_update": "收盤後報告更新",
}

CATEGORY_ACTION_ROUTE_DETAILS = {
    "vector_store": "確認 RAG embedding 模型、Chroma client/server 版本與向量庫連線；修復後重新補索引或重送任務。",
    "runtime_storage": "確認 report_dir、SQLite/資料庫檔案與備份目錄存在且程序具讀寫權限；修復後重送任務。",
}


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
            "summary": row.get("error_summary") or "-",
            "retry": "可重試" if row.get("retryable") else "需人工",
            "retry_kind": task_failure_retry_kind_label(row.get("retry_kind")),
            "action_route": task_failure_action_route(row),
            "action_route_detail": task_failure_action_route_detail(row),
            "next_action": row.get("next_action") or _fallback_failure_next_action(row),
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


def task_failure_action_route(row: dict) -> str:
    if _is_external_config_failure(row):
        return "外部配置缺失"
    if row.get("retryable"):
        return "一鍵重試"
    return "需人工處理"


def task_failure_action_route_detail(row: dict) -> str:
    category = str(row.get("error_category") or "").strip()
    if category in CATEGORY_ACTION_ROUTE_DETAILS:
        return CATEGORY_ACTION_ROUTE_DETAILS[category]
    return TASK_FAILURE_ACTION_ROUTE_DETAILS.get(task_failure_action_route(row), "-")


def task_failure_operation_label(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    return OPERATION_LABELS.get(text, text)


def task_failure_category_label(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    return CATEGORY_LABELS.get(text, text)


def task_failure_severity_label(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    return SEVERITY_LABELS.get(text, text)


def task_failure_retry_kind_label(value: object) -> str:
    return task_failure_operation_label(value)


def task_failure_next_steps_text(row: dict) -> str:
    category = str(row.get("error_category") or "").strip()
    if category == "task_queue":
        return (
            "到系統設定 > 維護 > 背景任務觀測確認 Redis/Celery 與 worker。；"
            "修復後重新送出任務。"
        )
    return _task_next_steps_text(row)


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


def _is_external_config_failure(row: dict) -> bool:
    category = str(row.get("error_category") or "").strip()
    if category in MANUAL_FAILURE_CATEGORIES:
        return False
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
            "Structured API",
            "結構化文件 API",
            "Visual RAG",
            "company filing 後援設定",
            "外部部署 readiness",
        )
    )


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
        return "查看任務狀態，確認 payload 是否支援自動重試。"
    return "缺少 task id；請從 run 明細檢查。"


def _task_next_steps_text(row: dict) -> str:
    next_steps = row.get("next_steps")
    if not isinstance(next_steps, list):
        return "-"
    steps = [str(step).strip() for step in next_steps if str(step).strip()]
    return "；".join(steps) if steps else "-"
