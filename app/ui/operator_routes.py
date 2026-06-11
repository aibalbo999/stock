from __future__ import annotations

from typing import Any


REPORT_CENTER_PAGE = "pages/02_報告中心.py"
ANALYSIS_PAGE = "pages/01_分析工作區.py"
DATA_ENRICHMENT_PAGE = "pages/03_資料補強.py"
SYSTEM_SETTINGS_PAGE = "pages/04_系統設定.py"

DATA_ENRICHMENT_OPERATION_LABELS = {
    "market_refresh": "刷新股價",
    "fundamentals_refresh": "刷新 5 年財報",
    "valuation_refresh": "刷新估值",
    "company_filings_fetch": "補抓公司文件",
    "manual_ingest": "匯入新聞/研究摘要",
}

DATA_ENRICHMENT_SECTION_BY_OPERATION = {
    "market_refresh": "market",
    "fundamentals_refresh": "market",
    "valuation_refresh": "market",
    "company_filings_fetch": "market",
    "manual_ingest": "manual",
}


def operator_route_target(route_hint: str | None) -> dict[str, Any]:
    route = str(route_hint or "").strip()
    if route.startswith("report:"):
        report_id = _route_suffix(route)
        parsed_report_id = _int_or_text(report_id)
        return {
            "page": REPORT_CENTER_PAGE,
            "session_updates": {"pending_selected_report_id": parsed_report_id},
            "caption": f"開啟報告中心並選取報告 #{report_id}",
        }
    if route == "report_center":
        return {
            "page": REPORT_CENTER_PAGE,
            "session_updates": {},
            "caption": "開啟報告中心",
        }
    if route == "data_enrichment":
        return {
            "page": DATA_ENRICHMENT_PAGE,
            "session_updates": {},
            "caption": "開啟資料補強",
        }
    if route.startswith("data_enrichment:"):
        return _data_enrichment_route_target(route)
    if route == "analysis":
        return {
            "page": ANALYSIS_PAGE,
            "session_updates": {},
            "caption": "回到分析工作區",
        }
    if route.startswith("task:"):
        task_id = _route_suffix(route)
        return {
            "page": SYSTEM_SETTINGS_PAGE,
            "session_updates": {
                "maintenance_inspect_task_id": task_id,
                "pending_maintenance_focus": "task_observability",
                "pending_settings_section": "maintenance",
            },
            "caption": f"開啟維護頁並檢視任務 {task_id}",
        }
    if route == "settings:ai_quota":
        return {
            "page": SYSTEM_SETTINGS_PAGE,
            "session_updates": {"pending_settings_section": "ai_quota"},
            "caption": "開啟系統設定的 AI 額度區",
        }
    if route == "settings:maintenance:local_defaults":
        return {
            "page": SYSTEM_SETTINGS_PAGE,
            "session_updates": {"pending_settings_section": "maintenance_local_defaults"},
            "caption": "開啟維護頁的本機 defaults 操作區",
        }
    if route == "settings:maintenance:structured_api":
        return {
            "page": SYSTEM_SETTINGS_PAGE,
            "session_updates": {"pending_settings_section": "maintenance_structured_api"},
            "caption": "開啟維護頁的公司文件結構化 API 免費驗證指令區",
        }
    if route == "settings:scope":
        return {
            "page": SYSTEM_SETTINGS_PAGE,
            "session_updates": {"pending_settings_section": "scope"},
            "caption": "開啟系統設定的股票範圍區",
        }
    if route == "settings:maintenance":
        return {
            "page": SYSTEM_SETTINGS_PAGE,
            "session_updates": {"pending_settings_section": "maintenance"},
            "caption": "開啟系統設定的維護區",
        }
    return {
        "page": SYSTEM_SETTINGS_PAGE,
        "session_updates": {"pending_settings_section": "maintenance"},
        "caption": "開啟系統設定檢查此建議",
    }


def _route_suffix(route: str) -> str:
    return route.split(":", 1)[1].strip()


def _int_or_text(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _data_enrichment_route_target(route: str) -> dict[str, Any]:
    parts = route.split(":", 2)
    operation = parts[1].strip() if len(parts) > 1 else ""
    tickers = _csv_values(parts[2]) if len(parts) > 2 else []
    section = DATA_ENRICHMENT_SECTION_BY_OPERATION.get(operation, "market")
    label = DATA_ENRICHMENT_OPERATION_LABELS.get(operation, "資料補強")
    session_updates: dict[str, Any] = {
        "pending_data_enrichment_section": section,
        "pending_data_enrichment_operation": operation,
    }
    if tickers:
        session_updates["pending_data_enrichment_tickers"] = tickers
    ticker_caption = f"：{'、'.join(tickers)}" if tickers else ""
    return {
        "page": DATA_ENRICHMENT_PAGE,
        "session_updates": session_updates,
        "caption": f"開啟資料補強，準備{label}{ticker_caption}",
    }


def _csv_values(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
