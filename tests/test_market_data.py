import asyncio
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.market import MarketDataClient
from app.db.models import Base
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.persistence import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    RiskClassificationRepository,
    ValuationMetricRepository,
)


def test_finmind_row_to_snapshot() -> None:
    snapshot = MarketDataClient._row_to_snapshot(
        {
            "date": "2026-05-22",
            "stock_id": "2330",
            "Trading_Volume": 123,
            "Trading_money": 456,
            "open": 1000.0,
            "max": 1010.0,
            "min": 990.0,
            "close": 1005.0,
            "spread": 5.0,
            "Trading_turnover": 789,
        }
    )

    assert snapshot.ticker == "2330"
    assert snapshot.trade_date == date(2026, 5, 22)
    assert snapshot.high == 1010.0
    assert snapshot.trading_volume == 123


def test_finmind_row_to_monthly_revenue() -> None:
    revenue = MarketDataClient._row_to_monthly_revenue(
        {
            "date": "2026-04-10",
            "stock_id": "2330",
            "revenue": "349567000000",
            "revenue_year": "2026",
            "revenue_month": "4",
        }
    )

    assert revenue.ticker == "2330"
    assert revenue.revenue_date == date(2026, 4, 10)
    assert revenue.revenue == 349567000000
    assert revenue.revenue_month == 4


def test_finmind_row_to_financial_metric() -> None:
    metric = MarketDataClient._row_to_financial_metric(
        {
            "date": "2026-03-31",
            "stock_id": "2330",
            "type": "營業收入",
            "value": "839254000000",
            "origin_name": "營業收入合計",
        },
        "income_statement",
        "TaiwanStockFinancialStatements",
    )

    assert metric.ticker == "2330"
    assert metric.report_date == date(2026, 3, 31)
    assert metric.statement_type == "income_statement"
    assert metric.metric == "營業收入"
    assert metric.value == 839254000000.0


def test_finmind_row_to_valuation_metric() -> None:
    valuation = MarketDataClient._row_to_valuation_metric(
        {
            "date": "2026-05-22",
            "stock_id": "2330",
            "PER": "24.5",
            "PBR": "5.8",
            "dividend_yield": "1.6",
        }
    )

    assert valuation.ticker == "2330"
    assert valuation.trade_date == date(2026, 5, 22)
    assert valuation.pe_ratio == 24.5
    assert valuation.pb_ratio == 5.8
    assert valuation.dividend_yield == 1.6


def test_latest_snapshots_collect_partial_errors(monkeypatch) -> None:
    client = MarketDataClient()

    async def fake_get_price_history(ticker: str, start_date: date, end_date: date):
        if ticker == "2382":
            raise TimeoutError("timeout")
        return [
            MarketSnapshot(ticker=ticker, trade_date=date(2026, 5, 20), close=100.0),
            MarketSnapshot(ticker=ticker, trade_date=date(2026, 5, 22), close=110.0),
        ]

    monkeypatch.setattr(client, "get_price_history", fake_get_price_history)

    snapshots, errors = asyncio.run(
        client.get_latest_snapshots_with_errors(
            ["2330", "2382"],
            date(2026, 5, 1),
            date(2026, 5, 22),
        )
    )

    assert [snapshot.ticker for snapshot in snapshots] == ["2330"]
    assert snapshots[0].trade_date == date(2026, 5, 22)
    assert len(errors) == 1
    assert errors[0].model_dump() == {
        "ticker": "2382",
        "dataset": "TaiwanStockPrice",
        "error": "timeout",
    }


def test_monthly_revenue_collect_partial_errors(monkeypatch) -> None:
    client = MarketDataClient()

    async def fake_get_monthly_revenue_history(ticker: str, start_date: date, end_date: date):
        if ticker == "2382":
            raise RuntimeError("rate limited")
        return [
            MonthlyRevenue(
                ticker=ticker,
                revenue_date=date(2026, 4, 10),
                revenue=125,
                revenue_year=2026,
                revenue_month=4,
            )
        ]

    monkeypatch.setattr(client, "get_monthly_revenue_history", fake_get_monthly_revenue_history)

    revenues, errors = asyncio.run(
        client.get_monthly_revenue_histories_with_errors(
            ["2330", "2382"],
            date(2025, 1, 1),
            date(2026, 5, 22),
        )
    )

    assert [revenue.ticker for revenue in revenues] == ["2330"]
    assert len(errors) == 1
    assert errors[0].model_dump() == {
        "ticker": "2382",
        "dataset": "TaiwanStockMonthRevenue",
        "error": "rate limited",
    }


def test_market_repository_upsert_and_latest() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = MarketRepository(session)
        repository.upsert_snapshots(
            [
                MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 21), close=1000.0),
                MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1010.0),
            ]
        )
        session.commit()

        latest = repository.latest_by_tickers(["2330"])

        assert len(latest) == 1
        assert latest[0].trade_date == date(2026, 5, 22)
        assert latest[0].close == 1010.0
    finally:
        session.close()


def test_monthly_revenue_repository_upsert_and_yoy() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = MonthlyRevenueRepository(session)
        repository.upsert_revenues(
            [
                MonthlyRevenue(
                    ticker="2330",
                    revenue_date=date(2025, 4, 10),
                    revenue=100,
                    revenue_year=2025,
                    revenue_month=4,
                ),
                MonthlyRevenue(
                    ticker="2330",
                    revenue_date=date(2026, 4, 10),
                    revenue=125,
                    revenue_year=2026,
                    revenue_month=4,
                ),
            ]
        )
        session.commit()

        latest = repository.latest_by_tickers(["2330"])

        assert len(latest) == 1
        assert latest[0].revenue_date == date(2026, 4, 10)
        assert latest[0].yoy_pct == 25.0
    finally:
        session.close()


def test_financial_and_valuation_repository_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        FinancialMetricRepository(session).upsert_metrics(
            [
                FinancialMetric(
                    ticker="2330",
                    report_date=date(2026, 3, 31),
                    statement_type="income_statement",
                    metric="營業收入",
                    value=1000.0,
                    origin_name="營業收入合計",
                    source="FinMind TaiwanStockFinancialStatements",
                )
            ]
        )
        ValuationMetricRepository(session).upsert_valuations(
            [
                ValuationMetric(
                    ticker="2330",
                    trade_date=date(2026, 5, 22),
                    pe_ratio=24.5,
                    pb_ratio=5.8,
                    dividend_yield=1.6,
                )
            ]
        )
        session.commit()

        metrics = FinancialMetricRepository(session).by_tickers(["2330"])
        valuations = ValuationMetricRepository(session).latest_by_tickers(["2330"])

        assert metrics[0].metric == "營業收入"
        assert metrics[0].value == 1000.0
        assert valuations[0].pe_ratio == 24.5
    finally:
        session.close()


def test_risk_classification_repository_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = RiskClassificationRepository(session)
        repository.upsert(
            document_id="doc-1",
            topic_hash="topic-a",
            classification="opportunity_or_growth",
            topic="需求成長",
            evidence="需求旺",
            confidence=0.9,
            keywords=["需求旺"],
            model="gemini-test",
        )
        session.commit()

        cached = repository.get("doc-1", "topic-a")

        assert cached["classification"] == "opportunity_or_growth"
        assert cached["topic_hash"] == "topic-a"
        assert cached["keywords"] == ["需求旺"]
        assert cached["model"] == "gemini-test"
    finally:
        session.close()
