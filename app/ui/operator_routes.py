from __future__ import annotations

from typing import Any


REPORT_CENTER_PAGE = "pages/02_報告中心.py"
ANALYSIS_PAGE = "pages/01_分析工作區.py"
DATA_ENRICHMENT_PAGE = "pages/03_資料補強.py"
SYSTEM_SETTINGS_PAGE = "pages/04_系統設定.py"


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
