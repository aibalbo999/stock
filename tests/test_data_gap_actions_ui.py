from __future__ import annotations

from app.ui.data_gap_actions import data_gap_action_items, data_gap_action_summary


def test_data_gap_action_items_map_follow_up_next_actions() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "request": {"topic": "AI 產業鏈", "tickers": ["2330", "2382"]},
            "next_actions": [
                {
                    "action": "refresh_market",
                    "tickers": ["2330"],
                    "target": "股價與量能",
                    "priority": "required",
                    "purpose": "required",
                    "reason": "缺少最新股價",
                    "next_step": "刷新股價",
                },
                {
                    "action": "ingest_company_filings",
                    "tickers": ["2382"],
                    "target": "公司公開文件",
                    "priority": "required",
                    "purpose": "required",
                    "reason": "缺少法說會簡報",
                    "next_step": "補抓公司文件",
                },
                {
                    "action": "rerun_analysis",
                    "tickers": ["2330", "2382"],
                    "target": "完整投資報告",
                    "priority": "required",
                    "purpose": "required",
                    "reason": "補強後重跑",
                    "next_step": "重跑報告",
                },
            ],
        },
    )

    assert [item["operation"] for item in items] == [
        "market_refresh",
        "company_filings_fetch",
        "report_follow_up",
    ]
    assert set(items[0]) == {
        "report_id",
        "topic",
        "ticker",
        "tickers",
        "gap_type",
        "action_label",
        "operation",
        "impact",
        "post_action_hint",
        "route_hint",
        "purpose",
        "priority",
    }
    assert items[0]["gap_type"] == "price"
    assert items[0]["route_hint"] == "data_enrichment"
    assert items[1]["action_label"] == "補抓公司文件"
    assert items[2]["route_hint"] == "report:12"
    assert items[2]["post_action_hint"] == "補強完成後重跑報告"


def test_data_gap_action_items_return_empty_without_gaps() -> None:
    assert data_gap_action_items({"report_id": 15}, {"next_actions": []}) == []
    assert data_gap_action_summary([]) == {
        "state": "ready",
        "label": "目前沒有必要資料缺口",
        "detail": "最新版報告沒有必補資料行動。",
    }


def test_data_gap_action_summary_counts_required_actions() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "next_actions": [
                {
                    "action": "refresh_financial_metrics",
                    "tickers": ["2330"],
                    "purpose": "required",
                },
                {"action": "refresh_valuations", "tickers": ["2330"], "purpose": "tracking"},
            ]
        },
    )

    assert data_gap_action_summary(items) == {
        "state": "attention",
        "label": "必補 1 項｜追蹤 1 項",
        "detail": "先處理必補資料，再重跑最新版報告。",
    }


def test_data_gap_action_items_ignore_unsupported_monthly_revenue_action() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "next_actions": [
                {
                    "action": "refresh_monthly_revenue",
                    "tickers": ["2330"],
                    "purpose": "required",
                }
            ]
        },
    )

    assert items == []


def test_data_gap_action_items_keep_distinct_gap_types_for_same_ticker_and_purpose() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "next_actions": [
                {
                    "action": "refresh_financial_metrics",
                    "tickers": ["2330"],
                    "purpose": "required",
                },
                {
                    "action": "refresh_valuations",
                    "tickers": ["2330"],
                    "purpose": "required",
                },
            ]
        },
    )

    assert [item["operation"] for item in items] == [
        "fundamentals_refresh",
        "valuation_refresh",
    ]


def test_data_gap_action_items_keep_same_action_with_different_target_or_reason() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "next_actions": [
                {
                    "action": "refresh_financial_metrics",
                    "tickers": ["2330"],
                    "purpose": "required",
                    "target": "五年財報",
                    "reason": "缺少近五年資料",
                },
                {
                    "action": "refresh_financial_metrics",
                    "tickers": ["2330"],
                    "purpose": "required",
                    "target": "財務比率",
                    "reason": "財務比率過舊",
                },
            ]
        },
    )

    assert len(items) == 2
    assert [item["impact"] for item in items] == [
        "刷新 5 年財報可改善「五年財報」：缺少近五年資料",
        "刷新 5 年財報可改善「財務比率」：財務比率過舊",
    ]


def test_data_gap_action_items_do_not_treat_priority_as_purpose() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "next_actions": [
                {
                    "action": "refresh_market",
                    "tickers": ["2330"],
                    "priority": "high",
                }
            ]
        },
    )

    assert items[0]["purpose"] == "tracking"
    assert items[0]["priority"] == "high"
    assert data_gap_action_summary(items) == {
        "state": "ready",
        "label": "必補 0 項｜追蹤 1 項",
        "detail": "目前只有追蹤型資料更新，可排在主要閱讀流程之後。",
    }


def test_data_gap_action_items_use_available_data_enrichment_route() -> None:
    items = data_gap_action_items(
        {"report_id": 12, "topic": "AI 產業鏈"},
        {
            "next_actions": [
                {"action": "refresh_market", "tickers": ["2330"]},
                {"action": "ingest_news", "tickers": ["2330"]},
            ]
        },
    )

    assert [item["route_hint"] for item in items] == ["data_enrichment", "data_enrichment"]
