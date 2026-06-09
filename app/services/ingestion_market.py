from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any


def allowed_market_tickers(
    *,
    mapper: Any,
    tickers: list[str],
    filter_allowed: bool,
) -> list[str]:
    requested = tickers or sorted(mapper.whitelist.allowed_tickers())
    return mapper.filter_allowed_tickers(requested) if filter_allowed else requested


async def refresh_market_snapshots(
    *,
    mapper: Any,
    market_client: Any,
    tickers: list[str],
    start_date: date,
    end_date: date,
    filter_allowed: bool,
    check_cancelled: Callable[[], None],
    session_scope_func: Callable,
    market_repository_cls: type,
    market_sources_func: Callable[[list], list[str]],
    stale_source_count_func: Callable[[list], int],
) -> dict:
    allowed = allowed_market_tickers(
        mapper=mapper,
        tickers=tickers,
        filter_allowed=filter_allowed,
    )
    check_cancelled()
    histories, errors = await market_client.get_price_histories_with_errors(
        allowed,
        start_date,
        end_date,
        force_refresh=True,
    )
    check_cancelled()
    all_snapshots = [snapshot for history in histories.values() for snapshot in history]
    latest_snapshots = [
        sorted(history, key=lambda snapshot: snapshot.trade_date)[-1]
        for history in histories.values()
        if history
    ]
    sources = market_sources_func(all_snapshots)
    with session_scope_func() as session:
        market_repository_cls(session).upsert_snapshots(all_snapshots)
    return {
        "requested_tickers": allowed,
        "stored": [snapshot.model_dump(mode="json") for snapshot in latest_snapshots],
        "stored_history_count": len(all_snapshots),
        "stale_source_count": stale_source_count_func(all_snapshots),
        "errors": [error.model_dump() for error in errors],
        "source": ", ".join(sources) if sources else "market data providers",
        "sources": sources,
    }


async def refresh_monthly_revenue_history(
    *,
    mapper: Any,
    market_client: Any,
    tickers: list[str],
    start_date: date,
    end_date: date,
    filter_allowed: bool,
    check_cancelled: Callable[[], None],
    session_scope_func: Callable,
    monthly_revenue_repository_cls: type,
    stale_source_count_func: Callable[[list], int],
) -> dict:
    allowed = allowed_market_tickers(
        mapper=mapper,
        tickers=tickers,
        filter_allowed=filter_allowed,
    )
    check_cancelled()
    revenues, errors = await market_client.get_monthly_revenue_histories_with_errors(
        allowed,
        start_date,
        end_date,
    )
    check_cancelled()
    with session_scope_func() as session:
        repository = monthly_revenue_repository_cls(session)
        repository.upsert_revenues(revenues)
        latest = repository.latest_by_tickers(allowed)
    return {
        "requested_tickers": allowed,
        "stored_count": len(revenues),
        "latest": [revenue.model_dump(mode="json") for revenue in latest],
        "stale_source_count": stale_source_count_func(revenues),
        "errors": [error.model_dump() for error in errors],
        "source": "FinMind TaiwanStockMonthRevenue",
    }


async def refresh_financial_metric_history(
    *,
    mapper: Any,
    market_client: Any,
    tickers: list[str],
    start_date: date,
    end_date: date,
    filter_allowed: bool,
    check_cancelled: Callable[[], None],
    session_scope_func: Callable,
    financial_metric_repository_cls: type,
    stale_source_count_func: Callable[[list], int],
) -> dict:
    allowed = allowed_market_tickers(
        mapper=mapper,
        tickers=tickers,
        filter_allowed=filter_allowed,
    )
    check_cancelled()
    metrics, errors = await market_client.get_financial_metrics_histories_with_errors(
        allowed,
        start_date,
        end_date,
    )
    check_cancelled()
    with session_scope_func() as session:
        financial_metric_repository_cls(session).upsert_metrics(metrics)
    return {
        "requested_tickers": allowed,
        "stored_count": len(metrics),
        "stale_source_count": stale_source_count_func(metrics),
        "errors": [error.model_dump() for error in errors],
        "source": "FinMind financial statements",
    }


async def refresh_valuation_metrics(
    *,
    mapper: Any,
    market_client: Any,
    tickers: list[str],
    start_date: date,
    end_date: date,
    filter_allowed: bool,
    check_cancelled: Callable[[], None],
    session_scope_func: Callable,
    valuation_metric_repository_cls: type,
    stale_source_count_func: Callable[[list], int],
) -> dict:
    allowed = allowed_market_tickers(
        mapper=mapper,
        tickers=tickers,
        filter_allowed=filter_allowed,
    )
    check_cancelled()
    valuations, errors = await market_client.get_latest_valuations_with_errors(
        allowed,
        start_date,
        end_date,
    )
    check_cancelled()
    with session_scope_func() as session:
        valuation_metric_repository_cls(session).upsert_valuations(valuations)
    return {
        "requested_tickers": allowed,
        "stored": [valuation.model_dump(mode="json") for valuation in valuations],
        "stale_source_count": stale_source_count_func(valuations),
        "errors": [error.model_dump() for error in errors],
        "source": "FinMind TaiwanStockPER",
    }


__all__ = [
    "allowed_market_tickers",
    "refresh_financial_metric_history",
    "refresh_market_snapshots",
    "refresh_monthly_revenue_history",
    "refresh_valuation_metrics",
]
