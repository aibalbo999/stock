from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.core.config import get_settings
from app.data_sources import (
    market_batch,
    market_cache_rescue,
    market_client_runtime,
    market_finmind,
    market_fugle,
    market_official_openapi,
    market_parsers,
)
from app.data_sources.market_provider_delegates import (
    FINMIND_RETRYABLE_HTTP_STATUSES as FINMIND_RETRYABLE_HTTP_STATUSES,
    FUGLE_RETRYABLE_HTTP_STATUSES as FUGLE_RETRYABLE_HTTP_STATUSES,
    MarketDataProviderUnavailable as MarketDataProviderUnavailable,
    MarketProviderDelegateMixin,
    ProviderCircuitBreaker as ProviderCircuitBreaker,
)
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.market_data_cache import RedisMarketDataCache


@dataclass(frozen=True)
class MarketFetchError:
    ticker: str
    dataset: str
    error: str

    def model_dump(self) -> dict:
        return {
            "ticker": self.ticker,
            "dataset": self.dataset,
            "error": self.error,
        }


class MarketDataClient(MarketProviderDelegateMixin):
    STALE_CACHE_SOURCE_MARKER = market_cache_rescue.STALE_CACHE_SOURCE_MARKER
    LATEST_ONLY_SOURCE_MARKER = "latest-only"
    TWSE_OPENAPI_BASE_URL = market_official_openapi.TWSE_OPENAPI_BASE_URL
    TPEX_OPENAPI_BASE_URL = market_official_openapi.TPEX_OPENAPI_BASE_URL
    TWSE_PRICE_ENDPOINT = market_official_openapi.TWSE_PRICE_ENDPOINT
    TWSE_VALUATION_ENDPOINT = market_official_openapi.TWSE_VALUATION_ENDPOINT
    TWSE_MONTHLY_REVENUE_ENDPOINT = market_official_openapi.TWSE_MONTHLY_REVENUE_ENDPOINT
    TPEX_PRICE_ENDPOINT = market_official_openapi.TPEX_PRICE_ENDPOINT
    TPEX_VALUATION_ENDPOINT = market_official_openapi.TPEX_VALUATION_ENDPOINT
    TPEX_MONTHLY_REVENUE_ENDPOINT = market_official_openapi.TPEX_MONTHLY_REVENUE_ENDPOINT
    TWSE_INCOME_STATEMENT_ENDPOINTS = market_official_openapi.TWSE_INCOME_STATEMENT_ENDPOINTS
    TWSE_BALANCE_SHEET_ENDPOINTS = market_official_openapi.TWSE_BALANCE_SHEET_ENDPOINTS
    TPEX_INCOME_STATEMENT_ENDPOINTS = market_official_openapi.TPEX_INCOME_STATEMENT_ENDPOINTS
    TPEX_BALANCE_SHEET_ENDPOINTS = market_official_openapi.TPEX_BALANCE_SHEET_ENDPOINTS
    FUGLE_HISTORICAL_CANDLES_URL = market_fugle.FUGLE_HISTORICAL_CANDLES_URL
    FUGLE_HISTORICAL_STATS_URL = market_fugle.FUGLE_HISTORICAL_STATS_URL

    def __init__(self, cancellation_checker: Callable[[], None] | None = None) -> None:
        self.settings = get_settings()
        self.cancellation_checker = cancellation_checker
        self.timeout = market_client_runtime.finmind_timeout(self.settings)
        self.fugle_timeout = market_client_runtime.fugle_timeout(self.settings)
        self.official_openapi_timeout = market_client_runtime.official_openapi_timeout(
            self.settings
        )
        self.concurrency = max(1, int(getattr(self.settings, "finmind_concurrency", 5)))
        self.cache = RedisMarketDataCache()
        self._circuit_breakers = market_client_runtime.provider_circuit_breakers(self.settings)

    def _check_cancelled(self) -> None:
        if self.cancellation_checker is not None:
            self.cancellation_checker()

    async def get_price_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        force_refresh: bool = False,
    ) -> list[MarketSnapshot]:
        if not force_refresh:
            cached = self.cache.get_price_history(ticker, start_date, end_date)
            if cached is not None:
                return cached

        try:
            snapshots = await self._fetch_price_history_uncached(ticker, start_date, end_date)
        except Exception:
            stale = self._get_stale_cache_rows("get_latest_price_history", ticker)
            if stale is not None:
                return stale
            raise
        if not snapshots:
            stale = self._get_stale_cache_rows("get_latest_price_history", ticker)
            if stale is not None:
                return stale
        self.cache.set_price_history(ticker, start_date, end_date, snapshots)
        return snapshots

    async def get_latest_snapshots(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        *,
        force_refresh: bool = False,
    ) -> list[MarketSnapshot]:
        snapshots, _errors = await self.get_latest_snapshots_with_errors(
            tickers,
            start_date,
            end_date,
            force_refresh=force_refresh,
        )
        return snapshots

    async def get_latest_snapshots_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        *,
        force_refresh: bool = False,
    ) -> tuple[list[MarketSnapshot], list[MarketFetchError]]:
        histories, errors = await self.get_price_histories_with_errors(
            tickers,
            start_date,
            end_date,
            force_refresh=force_refresh,
        )
        snapshots = market_batch.latest_rows_from_histories(
            histories, sort_key=lambda item: item.trade_date
        )
        return snapshots, errors

    async def get_price_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        *,
        force_refresh: bool = False,
    ) -> tuple[dict[str, list[MarketSnapshot]], list[MarketFetchError]]:
        dataset = "TaiwanStockPrice"
        results = await market_batch.fetch_ticker_rows(
            tickers=tickers,
            concurrency=self.concurrency,
            dataset=dataset,
            fetch_rows=lambda ticker: self.get_price_history(
                ticker,
                start_date,
                end_date,
                force_refresh=force_refresh,
            ),
            make_error=self._fetch_error,
            check_cancelled=self._check_cancelled,
        )
        return market_batch.collect_history_by_ticker(
            results,
            dataset=dataset,
            empty_error=lambda ticker, dataset: MarketFetchError(
                ticker=ticker,
                dataset=dataset,
                error="Market data providers returned no price rows for requested period",
            ),
            sort_key=lambda item: item.trade_date,
        )

    async def get_monthly_revenue_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        return await market_cache_rescue.get_or_fetch_with_rescue(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            cache_get=self.cache.get_monthly_revenue_history,
            cache_set=self.cache.set_monthly_revenue_history,
            fetch_primary=lambda: market_finmind.fetch_monthly_revenue(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                fetch_rows=self._fetch_finmind_rows,
            ),
            fetch_fallback=lambda: self._fetch_official_openapi_monthly_revenue(
                ticker,
                start_date,
                end_date,
            ),
            get_stale_rows=lambda: self._get_stale_cache_rows(
                "get_latest_monthly_revenue_history",
                ticker,
            ),
        )

    async def get_monthly_revenue_histories(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        revenues, _errors = await self.get_monthly_revenue_histories_with_errors(
            tickers, start_date, end_date
        )
        return revenues

    async def get_monthly_revenue_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[MonthlyRevenue], list[MarketFetchError]]:
        dataset = "TaiwanStockMonthRevenue"
        results = await market_batch.fetch_ticker_rows(
            tickers=tickers,
            concurrency=self.concurrency,
            dataset=dataset,
            fetch_rows=lambda ticker: self.get_monthly_revenue_history(
                ticker, start_date, end_date
            ),
            make_error=self._fetch_error,
            check_cancelled=self._check_cancelled,
        )
        return market_batch.collect_flat_rows(
            results,
            dataset=dataset,
            empty_error=lambda ticker, dataset: MarketFetchError(
                ticker=ticker,
                dataset=dataset,
                error="FinMind returned no monthly revenue rows for requested period",
            ),
        )

    async def get_financial_metrics_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[FinancialMetric]:
        return await market_cache_rescue.get_or_fetch_with_rescue(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            cache_get=self.cache.get_financial_metrics,
            cache_set=self.cache.set_financial_metrics,
            fetch_primary=lambda: market_finmind.fetch_financial_metrics(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                fetch_rows=self._fetch_finmind_rows,
            ),
            fetch_fallback=lambda: self._fetch_official_openapi_financial_metrics(
                ticker,
                start_date,
                end_date,
            ),
            get_stale_rows=lambda: self._get_stale_cache_rows(
                "get_latest_financial_metrics",
                ticker,
            ),
        )

    async def get_financial_metrics_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[FinancialMetric], list[MarketFetchError]]:
        dataset = "FinMindFinancialStatements"
        results = await market_batch.fetch_ticker_rows(
            tickers=tickers,
            concurrency=self.concurrency,
            dataset=dataset,
            fetch_rows=lambda ticker: self.get_financial_metrics_history(
                ticker, start_date, end_date
            ),
            make_error=self._fetch_error,
            check_cancelled=self._check_cancelled,
        )
        return market_batch.collect_flat_rows(
            results,
            dataset=dataset,
            empty_error=lambda ticker, dataset: MarketFetchError(
                ticker=ticker,
                dataset=dataset,
                error="FinMind returned no financial statement rows for requested period",
            ),
        )

    async def get_valuation_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetric]:
        return await market_cache_rescue.get_or_fetch_with_rescue(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            cache_get=self.cache.get_valuation_history,
            cache_set=self.cache.set_valuation_history,
            fetch_primary=lambda: market_finmind.fetch_valuation(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                fetch_rows=self._fetch_finmind_rows,
            ),
            fetch_fallback=lambda: self._fetch_official_openapi_valuation(
                ticker,
                start_date,
                end_date,
            ),
            get_stale_rows=lambda: self._get_stale_cache_rows(
                "get_latest_valuation_history",
                ticker,
            ),
        )

    async def get_latest_valuations_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[ValuationMetric], list[MarketFetchError]]:
        dataset = "TaiwanStockPER"
        results = await market_batch.fetch_ticker_rows(
            tickers=tickers,
            concurrency=self.concurrency,
            dataset=dataset,
            fetch_rows=lambda ticker: self.get_valuation_history(ticker, start_date, end_date),
            make_error=self._fetch_error,
            check_cancelled=self._check_cancelled,
        )
        return market_batch.collect_latest_rows(
            results,
            dataset=dataset,
            empty_error=lambda ticker, dataset: MarketFetchError(
                ticker=ticker,
                dataset=dataset,
                error="FinMind returned no valuation rows for requested period",
            ),
            sort_key=lambda item: item.trade_date,
        )

    @staticmethod
    def _fetch_error(ticker: str, dataset: str, exc: Exception) -> MarketFetchError:
        message = str(exc) or exc.__class__.__name__
        return MarketFetchError(ticker=ticker, dataset=dataset, error=message)

    def _get_stale_cache_rows(self, method_name: str, ticker: str):
        return market_cache_rescue.get_stale_cache_rows(
            self.cache,
            method_name=method_name,
            ticker=ticker,
            marker=self.STALE_CACHE_SOURCE_MARKER,
        )

    @classmethod
    def _mark_stale_cache_source(cls, row):
        return market_cache_rescue.mark_stale_cache_source(
            row,
            marker=cls.STALE_CACHE_SOURCE_MARKER,
        )

    @staticmethod
    def _row_to_snapshot(row: dict) -> MarketSnapshot:
        return market_parsers.row_to_snapshot(row)

    @staticmethod
    def _twse_openapi_row_to_snapshot(row: dict, ticker: str, source: str) -> MarketSnapshot:
        return market_parsers.twse_openapi_row_to_snapshot(row, ticker, source)

    @staticmethod
    def _tpex_openapi_row_to_snapshot(row: dict, ticker: str, source: str) -> MarketSnapshot:
        return market_parsers.tpex_openapi_row_to_snapshot(row, ticker, source)

    @staticmethod
    def _fugle_row_to_snapshot(row: dict, ticker: str) -> MarketSnapshot:
        return market_parsers.fugle_row_to_snapshot(row, ticker)

    @staticmethod
    def _fugle_stats_row_to_snapshot(row: dict, ticker: str) -> MarketSnapshot:
        return market_parsers.fugle_stats_row_to_snapshot(row, ticker)

    @staticmethod
    def _row_to_monthly_revenue(row: dict) -> MonthlyRevenue:
        return market_parsers.row_to_monthly_revenue(row)

    @staticmethod
    def _official_openapi_row_to_monthly_revenue(row: dict, source: str) -> MonthlyRevenue:
        return market_parsers.official_openapi_row_to_monthly_revenue(row, source)

    @staticmethod
    def _row_to_financial_metric(row: dict, statement_type: str, source: str) -> FinancialMetric:
        return market_parsers.row_to_financial_metric(row, statement_type, source)

    @staticmethod
    def _official_statement_metrics(
        row: dict,
        report_date: date,
        *,
        statement_type: str,
        metric_names: tuple[str, ...],
        source: str,
    ) -> list[FinancialMetric]:
        return market_parsers.official_statement_metrics(
            row,
            report_date,
            statement_type=statement_type,
            metric_names=metric_names,
            source=source,
        )

    @staticmethod
    def _row_to_valuation_metric(row: dict) -> ValuationMetric:
        return market_parsers.row_to_valuation_metric(row)

    @staticmethod
    def _twse_openapi_row_to_valuation_metric(
        row: dict, ticker: str, source: str
    ) -> ValuationMetric:
        return market_parsers.twse_openapi_row_to_valuation_metric(row, ticker, source)

    @staticmethod
    def _tpex_openapi_row_to_valuation_metric(
        row: dict, ticker: str, source: str
    ) -> ValuationMetric:
        return market_parsers.tpex_openapi_row_to_valuation_metric(row, ticker, source)

    @staticmethod
    def _official_statement_report_date(row: dict) -> date:
        return market_parsers.official_statement_report_date(row)

    @staticmethod
    def _roc_date_to_date(value) -> date:
        return market_parsers.roc_date_to_date(value)

    @staticmethod
    def _roc_year_to_ad(year: int) -> int:
        return market_parsers.roc_year_to_ad(year)

    @staticmethod
    def _float_or_none(value) -> float | None:
        return market_parsers.float_or_none(value)

    @staticmethod
    def _int_or_none(value) -> int | None:
        return market_parsers.int_or_none(value)
