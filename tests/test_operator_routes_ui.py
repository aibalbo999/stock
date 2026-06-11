from __future__ import annotations

from app.ui.operator_routes import operator_route_target


def test_operator_route_target_selects_report_before_opening_report_center() -> None:
    target = operator_route_target("report:15")

    assert target == {
        "page": "pages/02_報告中心.py",
        "session_updates": {"pending_selected_report_id": 15},
        "caption": "開啟報告中心並選取報告 #15",
    }


def test_operator_route_target_opens_data_enrichment_and_analysis_pages() -> None:
    assert operator_route_target("data_enrichment") == {
        "page": "pages/03_資料補強.py",
        "session_updates": {},
        "caption": "開啟資料補強",
    }
    assert operator_route_target("analysis") == {
        "page": "pages/01_分析工作區.py",
        "session_updates": {},
        "caption": "回到分析工作區",
    }


def test_operator_route_target_prefills_data_enrichment_operation() -> None:
    assert operator_route_target("data_enrichment:market_refresh:2330,2382") == {
        "page": "pages/03_資料補強.py",
        "session_updates": {
            "pending_data_enrichment_section": "market",
            "pending_data_enrichment_operation": "market_refresh",
            "pending_data_enrichment_tickers": ["2330", "2382"],
        },
        "caption": "開啟資料補強，準備刷新股價：2330、2382",
    }


def test_operator_route_target_prefills_manual_ingest_section() -> None:
    assert operator_route_target("data_enrichment:manual_ingest:2330") == {
        "page": "pages/03_資料補強.py",
        "session_updates": {
            "pending_data_enrichment_section": "manual",
            "pending_data_enrichment_operation": "manual_ingest",
            "pending_data_enrichment_tickers": ["2330"],
        },
        "caption": "開啟資料補強，準備匯入新聞/研究摘要：2330",
    }


def test_operator_route_target_preserves_task_for_maintenance_drilldown() -> None:
    target = operator_route_target("task:abc-123")

    assert target == {
        "page": "pages/04_系統設定.py",
        "session_updates": {
            "maintenance_inspect_task_id": "abc-123",
            "pending_maintenance_focus": "task_observability",
            "pending_settings_section": "maintenance",
        },
        "caption": "開啟維護頁並檢視任務 abc-123",
    }


def test_operator_route_target_maps_settings_sections() -> None:
    assert operator_route_target("settings:scope") == {
        "page": "pages/04_系統設定.py",
        "session_updates": {"pending_settings_section": "scope"},
        "caption": "開啟系統設定的股票範圍區",
    }
    assert operator_route_target("settings:ai_quota") == {
        "page": "pages/04_系統設定.py",
        "session_updates": {"pending_settings_section": "ai_quota"},
        "caption": "開啟系統設定的 AI 額度區",
    }
    assert operator_route_target("settings:maintenance") == {
        "page": "pages/04_系統設定.py",
        "session_updates": {"pending_settings_section": "maintenance"},
        "caption": "開啟系統設定的維護區",
    }
    assert operator_route_target("settings:maintenance:local_defaults") == {
        "page": "pages/04_系統設定.py",
        "session_updates": {"pending_settings_section": "maintenance_local_defaults"},
        "caption": "開啟維護頁的本機 defaults 操作區",
    }
    assert operator_route_target("settings:maintenance:structured_api") == {
        "page": "pages/04_系統設定.py",
        "session_updates": {"pending_settings_section": "maintenance_structured_api"},
        "caption": "開啟維護頁的公司文件結構化 API 區",
    }
