from __future__ import annotations

from collections.abc import Callable

from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.leading_signals import LeadingSignal, LeadingSignalAnalyzer
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.report_financial_assessment import peer_valuation_summary


def latest_market_snapshots(
    tickers: list[str], *, session_scope_func: Callable
) -> list[MarketSnapshot]:
    if not tickers:
        return []
    try:
        with session_scope_func() as session:
            return MarketRepository(session).latest_by_tickers(tickers)
    except Exception:
        return []


def latest_monthly_revenues(
    tickers: list[str], *, session_scope_func: Callable
) -> list[MonthlyRevenue]:
    if not tickers:
        return []
    try:
        with session_scope_func() as session:
            return MonthlyRevenueRepository(session).latest_by_tickers(tickers)
    except Exception:
        return []


def financial_metrics(tickers: list[str], *, session_scope_func: Callable) -> list[FinancialMetric]:
    if not tickers:
        return []
    try:
        with session_scope_func() as session:
            return FinancialMetricRepository(session).by_tickers(tickers)
    except Exception:
        return []


def latest_valuations(tickers: list[str], *, session_scope_func: Callable) -> list[ValuationMetric]:
    if not tickers:
        return []
    try:
        with session_scope_func() as session:
            return ValuationMetricRepository(session).latest_by_tickers(tickers)
    except Exception:
        return []


def leading_signals(
    tickers: list[str],
    valuation_metrics: list[ValuationMetric],
    *,
    session_scope_func: Callable,
) -> dict[str, LeadingSignal]:
    if not tickers:
        return {}
    try:
        with session_scope_func() as session:
            price_histories = MarketRepository(session).history_by_tickers(tickers, limit=90)
            revenue_histories = MonthlyRevenueRepository(session).history_by_tickers(
                tickers, limit=18
            )
    except Exception:
        price_histories = {}
        revenue_histories = {}
    valuations = {valuation.ticker: valuation for valuation in valuation_metrics}
    peer_summary = peer_valuation_summary(valuation_metrics)
    return LeadingSignalAnalyzer().build(
        tickers, price_histories, revenue_histories, valuations, peer_summary
    )
