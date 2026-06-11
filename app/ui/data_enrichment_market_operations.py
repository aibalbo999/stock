from __future__ import annotations


MARKET_DATA_OPERATIONS = {
    "market_refresh",
    "fundamentals_refresh",
    "valuation_refresh",
    "company_filings_fetch",
}

MARKET_OPERATION_METADATA = {
    "market_refresh": {
        "label": "刷新股價",
        "impact": "更新最新版報告的股價與成交量判讀。",
        "date_mode": "range",
    },
    "fundamentals_refresh": {
        "label": "刷新 5 年財報",
        "impact": "補齊五年財務與品質門檻需要的財報資料。",
        "date_mode": "six_years",
    },
    "valuation_refresh": {
        "label": "刷新估值",
        "impact": "更新本益比、股價淨值比與殖利率判讀。",
        "date_mode": "range",
    },
    "company_filings_fetch": {
        "label": "補抓公司文件",
        "impact": "補齊公司文件、法說會或公開資訊缺口。",
        "date_mode": "none",
    },
}

MARKET_OPERATION_ORDER = [
    "market_refresh",
    "fundamentals_refresh",
    "valuation_refresh",
    "company_filings_fetch",
]


def normalized_market_tickers(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tickers = []
    seen = set()
    for ticker in value:
        text = str(ticker).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        tickers.append(text)
    return tickers


def allowed_market_tickers(value: object, allowed_tickers: list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = set(allowed_tickers)
    return [str(ticker).strip() for ticker in value if str(ticker).strip() in allowed]


def default_market_tickers(allowed_tickers: list[str]) -> list[str]:
    return ["2330"] if "2330" in allowed_tickers else allowed_tickers[:1]


def task_queue_status_from_service_snapshot(service_snapshot: dict) -> dict:
    if not isinstance(service_snapshot, dict):
        return {}
    task_queue = service_snapshot.get("task_queue")
    return task_queue if isinstance(task_queue, dict) else {}


def task_queue_block_reason(task_queue: dict | None) -> str:
    if task_queue is None:
        return ""
    if not isinstance(task_queue, dict) or not task_queue:
        return "尚未取得背景任務狀態"
    if not task_queue.get("ready"):
        return "背景任務未就緒，請先到維護頁檢查背景任務佇列"
    if task_queue.get("worker_online") is False:
        return "背景任務未就緒，請先到維護頁檢查背景執行器"
    if "processing_ready" in task_queue and not task_queue.get("processing_ready"):
        return "背景任務未就緒，請先到維護頁檢查背景執行器"
    return ""


def market_data_operation_button_type(
    pending_operation: str | None,
    operation: str,
) -> str:
    pending = str(pending_operation or "").strip()
    if pending in MARKET_DATA_OPERATIONS:
        return "primary" if pending == operation else "secondary"
    return "primary" if operation == "market_refresh" else "secondary"


def market_operation_disabled_reason(
    operation: str,
    *,
    has_market_selection: bool,
    has_valid_market_range: bool,
    task_queue_block_reason: str = "",
) -> str:
    if task_queue_block_reason:
        return task_queue_block_reason
    if not has_market_selection:
        return "請先選擇至少一檔股票"
    if operation in {"market_refresh", "valuation_refresh"} and not has_valid_market_range:
        return "起始日期不可晚於結束日期"
    return ""
