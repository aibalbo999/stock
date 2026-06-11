from __future__ import annotations

from datetime import date
from pathlib import Path

from app.ui.data_enrichment_market_presenter import (
    market_cache_operator_summary,
    market_data_operation_button_type,
    market_operation_readiness_rows,
    market_submission_preflight_summary,
    pending_market_handoff_summary,
    pending_market_selection_state,
)


def test_market_presenter_is_streamlit_free() -> None:
    source = Path("app/ui/data_enrichment_market_presenter.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_market_presenter_keeps_pending_selection_and_handoff_logic() -> None:
    selection = pending_market_selection_state(["2330", "9999"], ["2330", "2382"])

    assert selection == {
        "selected": ["2330"],
        "rejected": ["9999"],
        "state": "attention",
        "detail": "建議股票未在目前白名單：9999。已先選取可用股票：2330。",
        "action_label": "檢查股票範圍",
        "route_hint": "settings:scope",
    }
    assert pending_market_handoff_summary(
        selected_market_tickers=["2330"],
        pending_operation="company_filings_fetch",
        selection_state=selection,
    )["next_step"] == "先處理白名單提醒，再確認背景任務後按「補抓公司文件」。"


def test_market_presenter_keeps_operation_preflight_logic() -> None:
    rows = market_operation_readiness_rows(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 10),
        market_end=date(2026, 6, 1),
        pending_operation="valuation_refresh",
        task_queue={"ready": True, "processing_ready": True, "worker_online": True},
    )
    by_operation = {row["operation"]: row for row in rows}

    assert market_data_operation_button_type("valuation_refresh", "valuation_refresh") == "primary"
    assert by_operation["valuation_refresh"]["disabled_reason"] == "起始日期不可晚於結束日期"
    assert by_operation["fundamentals_refresh"]["disabled_reason"] == "可送出背景任務"

    summary = market_submission_preflight_summary(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation="market_refresh",
        task_queue={"ready": False, "worker_online": True},
        confirmed=True,
    )
    assert summary["state"] == "blocked"
    assert summary["next_step"] == "背景任務未就緒，請先到維護頁檢查背景任務佇列。"


def test_market_presenter_keeps_cache_summary_logic() -> None:
    rows = market_cache_operator_summary(
        {
            "tickers": ["2330", "2382"],
            "market_snapshots": [
                {"ticker": "2330", "trade_date": "2026-06-10", "source": "finmind"},
            ],
            "valuations": [
                {"ticker": "2330", "trade_date": "2026-06-09", "source": "cached-stale"},
                {"ticker": "2382", "trade_date": "2026-06-09", "source": "fugle"},
            ],
            "company_filings": [],
            "financial_metric_count": 0,
        }
    )

    assert rows[0]["caption"] == "缺 1 檔；建議刷新股價。"
    assert rows[1]["caption"] == "含快取救援資料；建議刷新估值。"
    assert rows[2]["action_label"] == "刷新 5 年財報"
    assert rows[3]["action_label"] == "補抓公司文件"
