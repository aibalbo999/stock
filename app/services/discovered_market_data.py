from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from app.data_sources.market import MarketDataClient, MarketFetchError
from app.db.session import session_scope
from app.models.schemas import MarketSnapshot
from app.services.discovery_workflow import (
    discovery_market_history_days,
    discovery_valuation_history_days,
)
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.task_cancellation import TaskCancelledError


def merge_latest_by_ticker(
    tickers: list[str], fetched_items: list, cached_items: list, date_attr: str
) -> list:
    merged = {getattr(item, "ticker", ""): item for item in cached_items}
    for item in fetched_items:
        ticker = getattr(item, "ticker", "")
        if ticker not in tickers:
            continue
        current = merged.get(ticker)
        item_date = getattr(item, date_attr, None)
        current_date = getattr(current, date_attr, None)
        if current_date is None or (item_date is not None and item_date >= current_date):
            merged[ticker] = item
    return [merged[ticker] for ticker in tickers if ticker in merged]


def merge_financial_metric_history(fetched_metrics: list, cached_metrics: list) -> list:
    merged = {}
    for metric in [*cached_metrics, *fetched_metrics]:
        key = (
            getattr(metric, "ticker", ""),
            getattr(metric, "report_date", None),
            getattr(metric, "statement_type", ""),
            getattr(metric, "metric", ""),
        )
        merged[key] = metric
    return list(merged.values())


def market_timeout_errors(
    tickers: list[str], dataset: str, exc: Exception
) -> list[MarketFetchError]:
    message = f"{dataset} fetch timed out or failed: {str(exc) or exc.__class__.__name__}"
    return [MarketFetchError(ticker=ticker, dataset=dataset, error=message) for ticker in tickers]


class DiscoveredMarketDataService:
    def __init__(
        self,
        session_scope_factory: Callable = session_scope,
        market_client_cls=MarketDataClient,
        market_repository_cls=MarketRepository,
        monthly_revenue_repository_cls=MonthlyRevenueRepository,
        financial_metric_repository_cls=FinancialMetricRepository,
        valuation_metric_repository_cls=ValuationMetricRepository,
        cancellation_checker: Callable[[], None] | None = None,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.market_client_cls = market_client_cls
        self.market_repository_cls = market_repository_cls
        self.monthly_revenue_repository_cls = monthly_revenue_repository_cls
        self.financial_metric_repository_cls = financial_metric_repository_cls
        self.valuation_metric_repository_cls = valuation_metric_repository_cls
        self.cancellation_checker = cancellation_checker

    def _check_cancelled(self) -> None:
        if self.cancellation_checker is not None:
            self.cancellation_checker()

    def _market_client(self) -> Any:
        try:
            return self.market_client_cls(cancellation_checker=self._check_cancelled)
        except TypeError:
            return self.market_client_cls()

    async def fetch_and_persist_for_discovery(
        self,
        payload: Any,
        promoted_tickers: list[str],
        end_date: date,
    ) -> dict:
        self._check_cancelled()
        market_client = self._market_client()
        market_start_date = end_date - timedelta(days=discovery_market_history_days(payload))
        valuation_start_date = end_date - timedelta(days=discovery_valuation_history_days(payload))
        try:
            price_histories, market_errors = await asyncio.wait_for(
                self._get_price_histories_with_errors(
                    market_client,
                    promoted_tickers,
                    market_start_date,
                    end_date,
                ),
                timeout=60,
            )
        except Exception as exc:
            if isinstance(exc, TaskCancelledError):
                raise
            price_histories = {}
            market_errors = market_timeout_errors(promoted_tickers, "TaiwanStockPrice", exc)
        self._check_cancelled()
        snapshots = [
            sorted(history, key=lambda snapshot: snapshot.trade_date)[-1]
            for history in price_histories.values()
            if history
        ]
        price_history_snapshots = [
            snapshot for history in price_histories.values() for snapshot in history
        ]
        try:
            monthly_revenues, monthly_revenue_errors = await asyncio.wait_for(
                market_client.get_monthly_revenue_histories_with_errors(
                    promoted_tickers,
                    end_date - timedelta(days=450),
                    end_date,
                ),
                timeout=60,
            )
        except Exception as exc:
            if isinstance(exc, TaskCancelledError):
                raise
            monthly_revenues = []
            monthly_revenue_errors = market_timeout_errors(
                promoted_tickers,
                "TaiwanStockMonthRevenue",
                exc,
            )
        self._check_cancelled()
        try:
            financial_metrics, financial_metric_errors = await asyncio.wait_for(
                market_client.get_financial_metrics_histories_with_errors(
                    promoted_tickers,
                    end_date - timedelta(days=365 * 6),
                    end_date,
                ),
                timeout=90,
            )
        except Exception as exc:
            if isinstance(exc, TaskCancelledError):
                raise
            financial_metrics = []
            financial_metric_errors = market_timeout_errors(
                promoted_tickers,
                "FinMindFinancialStatements",
                exc,
            )
        self._check_cancelled()
        try:
            valuations, valuation_errors = await asyncio.wait_for(
                market_client.get_latest_valuations_with_errors(
                    promoted_tickers,
                    valuation_start_date,
                    end_date,
                ),
                timeout=45,
            )
        except Exception as exc:
            if isinstance(exc, TaskCancelledError):
                raise
            valuations = []
            valuation_errors = market_timeout_errors(promoted_tickers, "TaiwanStockPER", exc)
        self._check_cancelled()
        with self.session_scope_factory() as session:
            market_repository = self.market_repository_cls(session)
            monthly_repository = self.monthly_revenue_repository_cls(session)
            financial_repository = self.financial_metric_repository_cls(session)
            valuation_repository = self.valuation_metric_repository_cls(session)
            market_repository.upsert_snapshots(price_history_snapshots)
            monthly_repository.upsert_revenues(monthly_revenues)
            financial_repository.upsert_metrics(financial_metrics)
            valuation_repository.upsert_valuations(valuations)
            snapshots = merge_latest_by_ticker(
                promoted_tickers,
                snapshots,
                market_repository.latest_by_tickers(promoted_tickers),
                "trade_date",
            )
            financial_metrics = merge_financial_metric_history(
                financial_metrics,
                financial_repository.by_tickers(promoted_tickers),
            )
            valuations = merge_latest_by_ticker(
                promoted_tickers,
                valuations,
                valuation_repository.latest_by_tickers(promoted_tickers),
                "trade_date",
            )
            latest_monthly_revenues = monthly_repository.latest_by_tickers(promoted_tickers)
        return {
            "snapshots": snapshots,
            "price_history_snapshots": price_history_snapshots,
            "market_errors": market_errors,
            "monthly_revenues": monthly_revenues,
            "monthly_revenue_errors": monthly_revenue_errors,
            "latest_monthly_revenues": latest_monthly_revenues,
            "financial_metrics": financial_metrics,
            "financial_metric_errors": financial_metric_errors,
            "valuations": valuations,
            "valuation_errors": valuation_errors,
            "market_history_days": discovery_market_history_days(payload),
            "valuation_history_days": discovery_valuation_history_days(payload),
        }

    @staticmethod
    async def _get_price_histories_with_errors(
        market_client: Any,
        promoted_tickers: list[str],
        market_start_date: date,
        end_date: date,
    ) -> tuple[dict[str, list[MarketSnapshot]], list[MarketFetchError]]:
        try:
            return await market_client.get_price_histories_with_errors(
                promoted_tickers,
                market_start_date,
                end_date,
                force_refresh=True,
            )
        except TypeError:
            return await market_client.get_price_histories_with_errors(
                promoted_tickers,
                market_start_date,
                end_date,
            )
