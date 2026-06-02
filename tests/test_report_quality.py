from datetime import date

from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.report_quality import (
    build_report_quality_gate,
    market_provider_summary,
    market_trade_date_summary,
    render_quality_gate_markdown,
    should_recover_market_data_quality,
)


def test_market_provider_summary_groups_sources_and_stale_counts() -> None:
    summary = market_provider_summary(
        [
            MarketSnapshot(
                ticker="2330",
                trade_date=date(2026, 5, 29),
                close=1000,
                source="Fugle historical stats",
            ),
            MarketSnapshot(
                ticker="2382",
                trade_date=date(2026, 5, 29),
                close=300,
                source="FinMind TaiwanStockPrice; cached-stale",
            ),
            MarketSnapshot(
                ticker="2454",
                trade_date=date(2026, 5, 29),
                close=1200,
                source="TWSE OpenAPI STOCK_DAY_ALL; latest-only",
            ),
        ],
        [
            MonthlyRevenue(
                ticker="2330",
                revenue_date=date(2026, 4, 10),
                revenue=100,
                revenue_year=2026,
                revenue_month=4,
                source="FinMind TaiwanStockMonthRevenue",
            )
        ],
        [
            FinancialMetric(
                ticker="2330",
                report_date=date(2026, 3, 31),
                statement_type="income_statement",
                metric="營業收入",
                value=100.0,
                source="FinMind TaiwanStockFinancialStatements",
            )
        ],
        [
            ValuationMetric(
                ticker="2330",
                trade_date=date(2026, 5, 29),
                pe_ratio=20,
                source="FinMind TaiwanStockPER",
            )
        ],
    )

    assert summary["price_history"]["providers"] == ["Fugle", "FinMind", "TWSE OpenAPI"]
    assert summary["price_history"]["stale_count"] == 1
    assert summary["price_history"]["latest_only_count"] == 1
    assert summary["monthly_revenue"]["providers"] == ["FinMind"]
    assert summary["financial_metrics"]["row_count"] == 1
    assert summary["valuation"]["sources"] == ["FinMind TaiwanStockPER"]


def test_quality_gate_markdown_includes_market_provider_summary() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 12}},
        ["2330"],
        market_count=1,
        monthly_revenue_count=1,
        financial_metrics_count=8,
        valuation_count=1,
        market_provider_summary={
            "price_history": {"label": "股價", "providers": ["Fugle"], "stale_count": 0, "latest_only_count": 0},
            "monthly_revenue": {
                "label": "月營收",
                "providers": ["TWSE OpenAPI"],
                "stale_count": 0,
                "latest_only_count": 1,
            },
            "financial_metrics": {"label": "五年財務", "providers": ["FinMind"], "stale_count": 0},
            "valuation": {"label": "估值", "providers": ["FinMind"], "stale_count": 1, "latest_only_count": 0},
        },
        monthly_revenue_latest_only_count=1,
    )

    markdown = render_quality_gate_markdown(gate)

    assert (
        "市場資料來源：股價 Fugle；月營收 TWSE OpenAPI（含官方最新救援 1 筆）；"
        "五年財務 FinMind；估值 FinMind（含快取救援 1 筆）"
    ) in markdown
    assert "官方最新救援資料：股價 0 檔、月營收 1 檔、五年財務 0 檔、估值 0 檔" in markdown
    assert "不能代表完整歷史趨勢" in "；".join(gate["warnings"])
    assert gate["metrics"]["market_provider_summary"]["price_history"]["providers"] == ["Fugle"]


def test_quality_gate_warns_when_report_prices_lag_database_latest_date() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 12}},
        ["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=16,
        valuation_count=2,
        market_latest_trade_date=date(2026, 6, 1),
        market_latest_trade_date_coverage=0.5,
        market_database_latest_trade_date=date(2026, 6, 1),
        market_older_than_database_latest_count=1,
    )

    markdown = render_quality_gate_markdown(gate)

    assert "股價日期不一致" in "；".join(gate["warnings"])
    assert "最新可取得交易日：2026-06-01" in markdown
    assert "同日覆蓋率 50%" in markdown
    assert should_recover_market_data_quality(gate) is True


def test_quality_gate_adds_self_healing_plan_for_recoverable_gaps() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 4}},
        ["2330"],
        market_count=0,
        monthly_revenue_count=0,
        financial_metrics_count=0,
        valuation_count=0,
        monthly_revenue_stale_count=1,
    )

    plan = gate["self_healing"]
    action_types = [action["action_type"] for action in plan["actions"]]

    assert plan["status"] == "planned"
    assert "ingest_news" in action_types
    assert "refresh_market" in action_types
    assert "refresh_monthly_revenue" in action_types
    assert action_types[-1] == "rerun_analysis"
    assert "自癒補強計畫" in render_quality_gate_markdown(gate)


def test_quality_gate_self_healing_plans_market_recovery_for_trade_date_mismatch() -> None:
    gate = build_report_quality_gate(
        {"candidate_support": {"supported_ratio": 1.0}, "dynamic_queries": {"stored_count": 20}},
        ["2330", "2382"],
        market_count=2,
        monthly_revenue_count=2,
        financial_metrics_count=16,
        valuation_count=2,
        market_latest_trade_date=date(2026, 6, 2),
        market_latest_trade_date_coverage=0.5,
        market_database_latest_trade_date=date(2026, 6, 2),
        market_older_than_database_latest_count=1,
    )

    plan = gate["self_healing"]

    assert should_recover_market_data_quality(gate) is True
    assert "market_data_gap" in plan["triggers"]
    assert any(action["action_type"] == "refresh_market" for action in plan["actions"])


def test_market_trade_date_summary_counts_tickers_older_than_database_latest_date() -> None:
    summary = market_trade_date_summary(
        [
            MarketSnapshot(ticker="2330", trade_date=date(2026, 6, 1), close=1000),
            MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 29), close=300),
        ],
        ["2330", "2382"],
        date(2026, 6, 1),
    )

    assert summary["latest_trade_date"] == date(2026, 6, 1)
    assert summary["latest_trade_date_coverage"] == 0.5
    assert summary["older_than_database_latest_count"] == 1
