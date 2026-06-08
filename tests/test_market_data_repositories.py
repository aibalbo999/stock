from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services import market_repositories, persistence
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.persistence import (
    RiskClassificationRepository,
)


def test_market_repositories_are_reexported_from_persistence_for_compatibility() -> None:
    assert persistence.MarketRepository is market_repositories.MarketRepository
    assert persistence.MonthlyRevenueRepository is market_repositories.MonthlyRevenueRepository
    assert persistence.FinancialMetricRepository is market_repositories.FinancialMetricRepository
    assert persistence.ValuationMetricRepository is market_repositories.ValuationMetricRepository


def test_market_repositories_live_outside_persistence_module() -> None:
    persistence_source = Path("app/services/persistence.py").read_text()
    market_repository_source = Path("app/services/market_repositories.py").read_text()

    assert "class MarketRepository" not in persistence_source
    assert "class MonthlyRevenueRepository" not in persistence_source
    assert "class FinancialMetricRepository" not in persistence_source
    assert "class ValuationMetricRepository" not in persistence_source
    assert "class MarketRepository" in market_repository_source
    assert "class MonthlyRevenueRepository" in market_repository_source
    assert "class FinancialMetricRepository" in market_repository_source
    assert "class ValuationMetricRepository" in market_repository_source


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
        history = repository.history_by_tickers(["2330"], limit=10)
        assert [snapshot.trade_date for snapshot in history["2330"]] == [
            date(2026, 5, 21),
            date(2026, 5, 22),
        ]
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
