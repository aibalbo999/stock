from __future__ import annotations


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


def failure_category(failure: dict) -> str:
    raw_category = _text(failure.get("error_category")).casefold()
    if not raw_category:
        return "unknown"
    if raw_category in FAILURE_CATEGORY_MAP:
        return FAILURE_CATEGORY_MAP[raw_category]
    if raw_category in ALLOWED_RAW_FAILURE_CATEGORIES:
        return raw_category
    return "unknown"


def failure_severity(failure: dict, category: str) -> str:
    raw_severity = _text(failure.get("error_severity")).casefold()
    if raw_severity in {"critical", "error"}:
        return "critical"
    if raw_severity in {"warning", "warn"}:
        return "warning"
    if raw_severity == "info":
        return "info"
    return "critical" if category == "runtime_storage" else "warning"


def failure_title(category: str) -> str:
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


def failure_impact(category: str) -> str:
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


def failure_next_action(category: str, retryable: bool) -> str:
    if category == "whitelist":
        return "修正輸入後重試" if retryable else "檢查輸入與白名單"
    if retryable:
        return "到維護頁重試此任務"
    return "到維護頁查看失敗診斷"


def failure_action_label(category: str, retryable: bool) -> str:
    if retryable:
        return "重試任務"
    if category == "quota":
        return "查看額度"
    if category in {"external_config", "task_queue", "visual_rag", "data_source"}:
        return "修復配置"
    return "檢查任務"


def _text(value: object, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default
