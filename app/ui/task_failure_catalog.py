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
    "一鍵重試": "可由維護頁直接重試；若為額度限制，等額度恢復或切換後援模型或資料源後再重試。",
    "外部配置缺失": "先修復背景任務佇列/執行器、資料源 token、Structured API、Visual RAG 或文件後援設定，再重送任務。",
    "需人工處理": "任務輸入、範圍、向量庫/本機儲存或取消狀態需人工檢查，修正後從原工作流程重送。",
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
    "market_data_refresh": "市場資料刷新",
    "company_filings_fetch": "公司文件抓取",
    "manual_ingest": "手動資料匯入",
    "rss_fetch": "RSS 抓取",
    "visual_rag": "Visual RAG",
    "after_close_report_update": "收盤後報告更新",
    "maintenance_cleanup": "維護清理",
    "maintenance_operation": "維護操作",
    "maintenance_diagnostic": "維護診斷",
}

CATEGORY_ACTION_ROUTE_DETAILS = {
    "vector_store": "確認 RAG embedding 模型、Chroma client/server 版本與向量庫連線；修復後重新補索引或重送任務。",
    "runtime_storage": "確認 report_dir、SQLite/資料庫檔案與備份目錄存在且程序具讀寫權限；修復後重送任務。",
}


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


def task_failure_raw_next_steps_text(row: dict) -> str:
    next_steps = row.get("next_steps")
    if not isinstance(next_steps, list):
        return "-"
    steps = [str(step).strip() for step in next_steps if str(step).strip()]
    return "；".join(steps) if steps else "-"


def _is_external_config_failure(row: dict) -> bool:
    category = str(row.get("error_category") or "").strip()
    if category in MANUAL_FAILURE_CATEGORIES:
        return False
    if category in EXTERNAL_CONFIG_FAILURE_CATEGORIES:
        return True
    next_steps_text = task_failure_raw_next_steps_text(row)
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
