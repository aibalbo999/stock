import asyncio
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.discovered_market_data import DiscoveredMarketDataService, market_timeout_errors


def test_discovered_market_data_fetch_merges_cached_fallback_rows() -> None:
    captured = {
        "market_upserts": 0,
        "monthly_upserts": 0,
        "financial_upserts": 0,
        "valuation_upserts": 0,
    }

    class FakeMarketClient:
        async def get_price_histories_with_errors(self, tickers, start_date, end_date):
            return (
                {
                    "2330": [
                        MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200),
                        MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 30), close=1210),
                    ]
                },
                [],
            )

        async def get_monthly_revenue_histories_with_errors(self, tickers, start_date, end_date):
            return (
                [
                    MonthlyRevenue(
                        ticker="2330",
                        revenue_date=date(2026, 4, 30),
                        revenue=100,
                        revenue_year=2026,
                        revenue_month=4,
                    )
                ],
                [],
            )

        async def get_financial_metrics_histories_with_errors(self, tickers, start_date, end_date):
            return (
                [
                    FinancialMetric(
                        ticker="2330",
                        report_date=date(2026, 3, 31),
                        statement_type="income",
                        metric="revenue",
                        value=110,
                        source="fresh",
                    )
                ],
                [],
            )

        async def get_latest_valuations_with_errors(self, tickers, start_date, end_date):
            return (
                [
                    ValuationMetric(
                        ticker="2330",
                        trade_date=date(2026, 5, 30),
                        pe_ratio=20,
                    )
                ],
                [],
            )

    class FakeMarketRepository:
        def __init__(self, session):
            self.session = session

        def upsert_snapshots(self, snapshots):
            captured["market_upserts"] = len(snapshots)

        def latest_by_tickers(self, tickers):
            return [MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 29), close=300)]

    class FakeMonthlyRevenueRepository:
        def __init__(self, session):
            self.session = session

        def upsert_revenues(self, revenues):
            captured["monthly_upserts"] = len(revenues)

        def latest_by_tickers(self, tickers):
            return [MonthlyRevenue(ticker="2382", revenue_date=date(2026, 4, 30), revenue=50, revenue_year=2026, revenue_month=4)]

    class FakeFinancialMetricRepository:
        def __init__(self, session):
            self.session = session

        def upsert_metrics(self, metrics):
            captured["financial_upserts"] = len(metrics)

        def by_tickers(self, tickers):
            return [
                FinancialMetric(
                    ticker="2330",
                    report_date=date(2026, 3, 31),
                    statement_type="income",
                    metric="revenue",
                    value=100,
                    source="cached",
                )
            ]

    class FakeValuationMetricRepository:
        def __init__(self, session):
            self.session = session

        def upsert_valuations(self, valuations):
            captured["valuation_upserts"] = len(valuations)

        def latest_by_tickers(self, tickers):
            return [ValuationMetric(ticker="2382", trade_date=date(2026, 5, 29), pe_ratio=15)]

    @contextmanager
    def fake_session_scope():
        yield object()

    service = DiscoveredMarketDataService(
        session_scope_factory=fake_session_scope,
        market_client_cls=FakeMarketClient,
        market_repository_cls=FakeMarketRepository,
        monthly_revenue_repository_cls=FakeMonthlyRevenueRepository,
        financial_metric_repository_cls=FakeFinancialMetricRepository,
        valuation_metric_repository_cls=FakeValuationMetricRepository,
    )

    result = asyncio.run(
        service.fetch_and_persist_for_discovery(
            SimpleNamespace(lookback_days=14, analysis_mode="standard", deep_analysis=False),
            ["2330", "2382"],
            date(2026, 5, 31),
        )
    )

    assert [snapshot.ticker for snapshot in result["snapshots"]] == ["2330", "2382"]
    assert [snapshot.close for snapshot in result["snapshots"]] == [1210, 300]
    assert {metric.value for metric in result["financial_metrics"]} == {110}
    assert [valuation.ticker for valuation in result["valuations"]] == ["2330", "2382"]
    assert [revenue.ticker for revenue in result["latest_monthly_revenues"]] == ["2382"]
    assert captured == {
        "market_upserts": 2,
        "monthly_upserts": 1,
        "financial_upserts": 1,
        "valuation_upserts": 1,
    }


def test_discovered_market_data_timeout_errors_are_per_ticker() -> None:
    errors = market_timeout_errors(["2330", "2382"], "TaiwanStockPrice", RuntimeError("timeout"))

    assert [error.ticker for error in errors] == ["2330", "2382"]
    assert all(error.dataset == "TaiwanStockPrice" for error in errors)
    assert "timeout" in errors[0].error
