from __future__ import annotations

import asyncio
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import time

import httpx

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.market_data_cache import RedisMarketDataCache
from app.services.task_cancellation import TaskCancelledError

FINMIND_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
FUGLE_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


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


class MarketDataProviderUnavailable(RuntimeError):
    """Raised when a configured market data provider cannot be used."""


class ProviderCircuitBreaker:
    def __init__(
        self,
        provider: str,
        *,
        enabled: bool,
        failure_threshold: int,
        recovery_seconds: float,
        monotonic_clock=time.monotonic,
    ) -> None:
        self.provider = provider
        self.enabled = bool(enabled)
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        self.monotonic_clock = monotonic_clock
        self.failure_count = 0
        self.opened_at: float | None = None

    def configure(
        self,
        *,
        enabled: bool,
        failure_threshold: int,
        recovery_seconds: float,
    ) -> None:
        self.enabled = bool(enabled)
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        if not self.enabled:
            self.failure_count = 0
            self.opened_at = None

    def before_call(self) -> None:
        if not self.enabled or self.opened_at is None:
            return
        elapsed = self.monotonic_clock() - self.opened_at
        if elapsed >= self.recovery_seconds:
            self.opened_at = None
            return
        raise MarketDataProviderUnavailable(
            f"{self.provider} circuit breaker is open; retry after {self.recovery_seconds - elapsed:.1f}s"
        )

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        if not self.enabled:
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = self.monotonic_clock()


class MarketDataClient:
    STALE_CACHE_SOURCE_MARKER = "cached-stale"
    LATEST_ONLY_SOURCE_MARKER = "latest-only"
    TWSE_OPENAPI_BASE_URL = "https://openapi.twse.com.tw/v1"
    TPEX_OPENAPI_BASE_URL = "https://www.tpex.org.tw/openapi/v1"
    TWSE_PRICE_ENDPOINT = f"{TWSE_OPENAPI_BASE_URL}/exchangeReport/STOCK_DAY_ALL"
    TWSE_VALUATION_ENDPOINT = f"{TWSE_OPENAPI_BASE_URL}/exchangeReport/BWIBBU_ALL"
    TWSE_MONTHLY_REVENUE_ENDPOINT = f"{TWSE_OPENAPI_BASE_URL}/opendata/t187ap05_L"
    TPEX_PRICE_ENDPOINT = f"{TPEX_OPENAPI_BASE_URL}/tpex_mainboard_quotes"
    TPEX_VALUATION_ENDPOINT = f"{TPEX_OPENAPI_BASE_URL}/tpex_mainboard_peratio_analysis"
    TPEX_MONTHLY_REVENUE_ENDPOINT = f"{TPEX_OPENAPI_BASE_URL}/mopsfin_t187ap05_O"
    TWSE_INCOME_STATEMENT_ENDPOINTS = (
        "opendata/t187ap06_L_ci",
        "opendata/t187ap06_L_basi",
        "opendata/t187ap06_L_bd",
        "opendata/t187ap06_L_fh",
        "opendata/t187ap06_L_ins",
        "opendata/t187ap06_L_mim",
    )
    TWSE_BALANCE_SHEET_ENDPOINTS = (
        "opendata/t187ap07_L_ci",
        "opendata/t187ap07_L_basi",
        "opendata/t187ap07_L_bd",
        "opendata/t187ap07_L_fh",
        "opendata/t187ap07_L_ins",
        "opendata/t187ap07_L_mim",
    )
    TPEX_INCOME_STATEMENT_ENDPOINTS = (
        "mopsfin_t187ap06_O_ci",
        "mopsfin_t187ap06_O_basi",
        "mopsfin_t187ap06_O_bd",
        "mopsfin_t187ap06_O_fh",
        "mopsfin_t187ap06_O_ins",
        "mopsfin_t187ap06_O_mim",
    )
    TPEX_BALANCE_SHEET_ENDPOINTS = (
        "mopsfin_t187ap07_O_ci",
        "mopsfin_t187ap07_O_basi",
        "mopsfin_t187ap07_O_bd",
        "mopsfin_t187ap07_O_fh",
        "mopsfin_t187ap07_O_ins",
        "mopsfin_t187ap07_O_mim",
    )
    FUGLE_HISTORICAL_CANDLES_URL = (
        "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{ticker}"
    )
    FUGLE_HISTORICAL_STATS_URL = (
        "https://api.fugle.tw/marketdata/v1.0/stock/historical/stats/{ticker}"
    )

    def __init__(self, cancellation_checker: Callable[[], None] | None = None) -> None:
        self.settings = get_settings()
        self.cancellation_checker = cancellation_checker
        self.timeout = httpx.Timeout(
            max(1.0, float(getattr(self.settings, "finmind_timeout_seconds", 20.0))),
            connect=max(1.0, float(getattr(self.settings, "finmind_connect_timeout_seconds", 8.0))),
        )
        self.fugle_timeout = httpx.Timeout(
            max(1.0, float(getattr(self.settings, "fugle_timeout_seconds", 20.0))),
            connect=max(1.0, float(getattr(self.settings, "fugle_connect_timeout_seconds", 8.0))),
        )
        self.official_openapi_timeout = httpx.Timeout(
            max(1.0, float(getattr(self.settings, "market_official_openapi_timeout_seconds", 15.0))),
            connect=max(
                1.0,
                min(
                    8.0,
                    float(getattr(self.settings, "market_official_openapi_timeout_seconds", 15.0)),
                ),
            ),
        )
        self.concurrency = max(1, int(getattr(self.settings, "finmind_concurrency", 5)))
        self.cache = RedisMarketDataCache()
        self._circuit_breakers = {
            "finmind": ProviderCircuitBreaker(
                "FinMind",
                enabled=self._provider_circuit_setting("finmind", "enabled", True),
                failure_threshold=self._provider_circuit_setting("finmind", "failure_threshold", 5),
                recovery_seconds=self._provider_circuit_setting("finmind", "recovery_seconds", 60.0),
            ),
            "fugle": ProviderCircuitBreaker(
                "Fugle",
                enabled=self._provider_circuit_setting("fugle", "enabled", True),
                failure_threshold=self._provider_circuit_setting("fugle", "failure_threshold", 5),
                recovery_seconds=self._provider_circuit_setting("fugle", "recovery_seconds", 60.0),
            ),
        }

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
        snapshots = [
            sorted(history, key=lambda item: item.trade_date)[-1]
            for history in histories.values()
            if history
        ]
        return snapshots, errors

    async def get_price_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        *,
        force_refresh: bool = False,
    ) -> tuple[dict[str, list[MarketSnapshot]], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                self._check_cancelled()
                try:
                    return (
                        ticker,
                        await self.get_price_history(
                            ticker,
                            start_date,
                            end_date,
                            force_refresh=force_refresh,
                        ),
                        None,
                    )
                except TaskCancelledError:
                    raise
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "TaiwanStockPrice", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        histories: dict[str, list[MarketSnapshot]] = {}
        errors: list[MarketFetchError] = []
        for ticker, history, error in results:
            if error:
                errors.append(error)
                continue
            if history:
                histories[ticker] = sorted(history, key=lambda item: item.trade_date)
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="TaiwanStockPrice",
                        error="Market data providers returned no price rows for requested period",
                    )
                )
                histories[ticker] = []
        return histories, errors

    async def get_monthly_revenue_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        cached = self.cache.get_monthly_revenue_history(ticker, start_date, end_date)
        if cached is not None:
            return cached

        try:
            rows = await self._fetch_finmind_rows("TaiwanStockMonthRevenue", ticker, start_date, end_date)
            revenues = [self._row_to_monthly_revenue(row) for row in rows]
        except Exception:
            revenues = await self._fetch_official_openapi_monthly_revenue(ticker, start_date, end_date)
            if revenues:
                self.cache.set_monthly_revenue_history(ticker, start_date, end_date, revenues)
                return revenues
            stale = self._get_stale_cache_rows("get_latest_monthly_revenue_history", ticker)
            if stale is not None:
                return stale
            raise
        if not revenues:
            revenues = await self._fetch_official_openapi_monthly_revenue(ticker, start_date, end_date)
            if revenues:
                self.cache.set_monthly_revenue_history(ticker, start_date, end_date, revenues)
                return revenues
            stale = self._get_stale_cache_rows("get_latest_monthly_revenue_history", ticker)
            if stale is not None:
                return stale
        self.cache.set_monthly_revenue_history(ticker, start_date, end_date, revenues)
        return revenues

    async def get_monthly_revenue_histories(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        revenues, _errors = await self.get_monthly_revenue_histories_with_errors(tickers, start_date, end_date)
        return revenues

    async def get_monthly_revenue_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[MonthlyRevenue], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                self._check_cancelled()
                try:
                    return ticker, await self.get_monthly_revenue_history(ticker, start_date, end_date), None
                except TaskCancelledError:
                    raise
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "TaiwanStockMonthRevenue", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        revenues: list[MonthlyRevenue] = []
        errors: list[MarketFetchError] = []
        for ticker, ticker_revenues, error in results:
            if error:
                errors.append(error)
                continue
            if ticker_revenues:
                revenues.extend(ticker_revenues)
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="TaiwanStockMonthRevenue",
                        error="FinMind returned no monthly revenue rows for requested period",
                    )
                )
        return revenues, errors

    async def get_financial_metrics_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[FinancialMetric]:
        cached = self.cache.get_financial_metrics(ticker, start_date, end_date)
        if cached is not None:
            return cached

        datasets = {
            "TaiwanStockFinancialStatements": "income_statement",
            "TaiwanStockBalanceSheet": "balance_sheet",
            "TaiwanStockCashFlowsStatement": "cash_flow",
        }
        metrics: list[FinancialMetric] = []
        try:
            for dataset, statement_type in datasets.items():
                rows = await self._fetch_finmind_rows(dataset, ticker, start_date, end_date)
                metrics.extend(
                    self._row_to_financial_metric(row, statement_type, dataset)
                    for row in rows
                    if self._float_or_none(row.get("value")) is not None
                )
        except Exception:
            metrics = await self._fetch_official_openapi_financial_metrics(
                ticker,
                start_date,
                end_date,
            )
            if metrics:
                self.cache.set_financial_metrics(ticker, start_date, end_date, metrics)
                return metrics
            stale = self._get_stale_cache_rows("get_latest_financial_metrics", ticker)
            if stale is not None:
                return stale
            raise
        if not metrics:
            metrics = await self._fetch_official_openapi_financial_metrics(
                ticker,
                start_date,
                end_date,
            )
            if metrics:
                self.cache.set_financial_metrics(ticker, start_date, end_date, metrics)
                return metrics
            stale = self._get_stale_cache_rows("get_latest_financial_metrics", ticker)
            if stale is not None:
                return stale
        self.cache.set_financial_metrics(ticker, start_date, end_date, metrics)
        return metrics

    async def get_financial_metrics_histories_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[FinancialMetric], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                self._check_cancelled()
                try:
                    return ticker, await self.get_financial_metrics_history(ticker, start_date, end_date), None
                except TaskCancelledError:
                    raise
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "FinMindFinancialStatements", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        metrics: list[FinancialMetric] = []
        errors: list[MarketFetchError] = []
        for ticker, ticker_metrics, error in results:
            if error:
                errors.append(error)
                continue
            if ticker_metrics:
                metrics.extend(ticker_metrics)
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="FinMindFinancialStatements",
                        error="FinMind returned no financial statement rows for requested period",
                    )
                )
        return metrics, errors

    async def get_valuation_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetric]:
        cached = self.cache.get_valuation_history(ticker, start_date, end_date)
        if cached is not None:
            return cached

        try:
            rows = await self._fetch_finmind_rows("TaiwanStockPER", ticker, start_date, end_date)
            valuations = [self._row_to_valuation_metric(row) for row in rows]
        except Exception:
            valuations = await self._fetch_official_openapi_valuation(ticker, start_date, end_date)
            if valuations:
                self.cache.set_valuation_history(ticker, start_date, end_date, valuations)
                return valuations
            stale = self._get_stale_cache_rows("get_latest_valuation_history", ticker)
            if stale is not None:
                return stale
            raise
        if not valuations:
            valuations = await self._fetch_official_openapi_valuation(ticker, start_date, end_date)
            if valuations:
                self.cache.set_valuation_history(ticker, start_date, end_date, valuations)
                return valuations
            stale = self._get_stale_cache_rows("get_latest_valuation_history", ticker)
            if stale is not None:
                return stale
        self.cache.set_valuation_history(ticker, start_date, end_date, valuations)
        return valuations

    async def get_latest_valuations_with_errors(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[list[ValuationMetric], list[MarketFetchError]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch_one(ticker: str):
            async with semaphore:
                self._check_cancelled()
                try:
                    return ticker, await self.get_valuation_history(ticker, start_date, end_date), None
                except TaskCancelledError:
                    raise
                except Exception as exc:
                    return ticker, [], self._fetch_error(ticker, "TaiwanStockPER", exc)

        results = await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))
        valuations: list[ValuationMetric] = []
        errors: list[MarketFetchError] = []
        for ticker, history, error in results:
            if error:
                errors.append(error)
                continue
            if history:
                valuations.append(sorted(history, key=lambda item: item.trade_date)[-1])
            else:
                errors.append(
                    MarketFetchError(
                        ticker=ticker,
                        dataset="TaiwanStockPER",
                        error="FinMind returned no valuation rows for requested period",
                    )
                )
        return valuations, errors

    @staticmethod
    def _fetch_error(ticker: str, dataset: str, exc: Exception) -> MarketFetchError:
        message = str(exc) or exc.__class__.__name__
        return MarketFetchError(ticker=ticker, dataset=dataset, error=message)

    def _get_stale_cache_rows(self, method_name: str, ticker: str):
        getter = getattr(self.cache, method_name, None)
        if not callable(getter):
            return None
        try:
            rows = getter(ticker)
        except Exception:
            return None
        if not rows:
            return None
        return [self._mark_stale_cache_source(row) for row in rows]

    @classmethod
    def _mark_stale_cache_source(cls, row):
        source = str(getattr(row, "source", "") or "")
        if cls.STALE_CACHE_SOURCE_MARKER in source:
            return row
        if not source:
            return row.model_copy(update={"source": cls.STALE_CACHE_SOURCE_MARKER})
        suffix = f"; {cls.STALE_CACHE_SOURCE_MARKER}"
        max_source_length = 100
        trimmed_source = source[: max(0, max_source_length - len(suffix))]
        return row.model_copy(update={"source": f"{trimmed_source}{suffix}"})

    async def _fetch_finmind_rows(
        self,
        dataset: str,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        if not self.settings.finmind_token and not self.finmind_public_fallback_enabled:
            raise MarketDataProviderUnavailable(
                "FinMind token is not configured and public fallback is disabled"
            )
        self._before_provider_request("finmind")
        params = {
            "dataset": dataset,
            "data_id": ticker,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        headers = {}
        if self.settings.finmind_token:
            headers["Authorization"] = f"Bearer {self.settings.finmind_token}"

        last_error: Exception | None = None
        for attempt in range(self.finmind_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(
                        "https://api.finmindtrade.com/api/v4/data",
                        params=params,
                        headers=headers,
                    )
                    response.raise_for_status()
                self._record_provider_success("finmind")
                return response.json().get("data", [])
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not self._should_retry_status(exc.response.status_code, attempt):
                    if exc.response.status_code in FINMIND_RETRYABLE_HTTP_STATUSES:
                        self._record_provider_failure("finmind")
                    raise
                await self._sleep_before_retry(exc.response, attempt)
            except (httpx.TransportError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.finmind_max_retries:
                    self._record_provider_failure("finmind")
                    raise
                await self._sleep_before_retry(None, attempt)
        if last_error:
            raise last_error
        return []

    async def _fetch_price_history_uncached(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketSnapshot]:
        last_error: Exception | None = None
        skipped_provider_error: Exception | None = None
        attempted_provider = False

        providers = self._market_price_provider_order()
        if self.official_openapi_fallback_enabled and "official_openapi" not in providers:
            providers.append("official_openapi")
        for provider in providers:
            try:
                if provider == "finmind":
                    attempted_provider = True
                    rows = await self._fetch_finmind_rows(
                        "TaiwanStockPrice",
                        ticker,
                        start_date,
                        end_date,
                    )
                    snapshots = [self._row_to_snapshot(row) for row in rows]
                elif provider == "fugle":
                    if not self.fugle_api_key:
                        skipped_provider_error = MarketDataProviderUnavailable(
                            "Fugle API key is not configured"
                        )
                        continue
                    attempted_provider = True
                    snapshots = await self._fetch_fugle_price_history(
                        ticker,
                        start_date,
                        end_date,
                    )
                elif provider == "official_openapi":
                    attempted_provider = True
                    snapshots = await self._fetch_official_openapi_price_snapshot(
                        ticker,
                        start_date,
                        end_date,
                    )
                else:
                    continue
            except Exception as exc:
                last_error = exc
                continue
            if snapshots:
                return snapshots

        if last_error is not None:
            raise last_error
        if not attempted_provider and skipped_provider_error is not None:
            raise skipped_provider_error
        return []

    async def _fetch_fugle_price_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketSnapshot]:
        candle_error: Exception | None = None
        try:
            rows = await self._fetch_fugle_historical_candle_rows(ticker, start_date, end_date)
            snapshots = [self._fugle_row_to_snapshot(row, ticker) for row in rows]
            if snapshots:
                return snapshots
        except Exception as exc:
            candle_error = exc

        try:
            row = await self._fetch_fugle_historical_stats_row(ticker)
            if row:
                snapshot = self._fugle_stats_row_to_snapshot(row, ticker)
                if start_date <= snapshot.trade_date <= end_date:
                    return [snapshot]
        except Exception as stats_error:
            if candle_error is not None:
                raise candle_error from stats_error
            raise

        if candle_error is not None:
            raise candle_error
        return []

    async def _fetch_fugle_historical_candle_rows(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        if not self.fugle_api_key:
            raise MarketDataProviderUnavailable("Fugle API key is not configured")

        params = {
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "timeframe": "D",
            "fields": "open,high,low,close,volume,turnover,change",
            "sort": "asc",
        }
        url = self.FUGLE_HISTORICAL_CANDLES_URL.format(ticker=ticker)
        payload = await self._fetch_fugle_json(url, params=params)
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if isinstance(data, dict):
            data = data.get("candles", [])
        return data if isinstance(data, list) else []

    async def _fetch_fugle_historical_stats_row(self, ticker: str) -> dict:
        if not self.fugle_api_key:
            raise MarketDataProviderUnavailable("Fugle API key is not configured")

        payload = await self._fetch_fugle_json(
            self.FUGLE_HISTORICAL_STATS_URL.format(ticker=ticker),
            params={},
        )
        return payload if isinstance(payload, dict) else {}

    async def _fetch_fugle_json(self, url: str, *, params: dict) -> dict:
        headers = {"X-API-KEY": self.fugle_api_key}
        self._before_provider_request("fugle")
        last_error: Exception | None = None
        for attempt in range(self.fugle_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.fugle_timeout) as client:
                    response = await client.get(url, params=params, headers=headers)
                    response.raise_for_status()
                self._record_provider_success("fugle")
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not self._should_retry_fugle_status(exc.response.status_code, attempt):
                    if exc.response.status_code in FUGLE_RETRYABLE_HTTP_STATUSES:
                        self._record_provider_failure("fugle")
                    raise
                await self._sleep_before_fugle_retry(exc.response, attempt)
            except (httpx.TransportError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.fugle_max_retries:
                    self._record_provider_failure("fugle")
                    raise
                await self._sleep_before_fugle_retry(None, attempt)
        if last_error:
            raise last_error
        return {}

    async def _fetch_official_openapi_price_snapshot(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketSnapshot]:
        if not self.official_openapi_fallback_enabled:
            return []
        for endpoint, source, converter in (
            (
                self.TWSE_PRICE_ENDPOINT,
                "TWSE OpenAPI STOCK_DAY_ALL",
                self._twse_openapi_row_to_snapshot,
            ),
            (
                self.TPEX_PRICE_ENDPOINT,
                "TPEx OpenAPI tpex_mainboard_quotes",
                self._tpex_openapi_row_to_snapshot,
            ),
        ):
            row = self._find_official_row(await self._fetch_official_openapi_rows(endpoint), ticker)
            if not row:
                continue
            snapshot = converter(row, ticker, self._latest_only_source(source))
            if start_date <= snapshot.trade_date <= end_date:
                return [snapshot]
        return []

    async def _fetch_official_openapi_monthly_revenue(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        if not self.official_openapi_fallback_enabled:
            return []
        for endpoint, source in (
            (self.TWSE_MONTHLY_REVENUE_ENDPOINT, "TWSE OpenAPI t187ap05_L"),
            (self.TPEX_MONTHLY_REVENUE_ENDPOINT, "TPEx OpenAPI mopsfin_t187ap05_O"),
        ):
            row = self._find_official_row(await self._fetch_official_openapi_rows(endpoint), ticker)
            if not row:
                continue
            revenue = self._official_openapi_row_to_monthly_revenue(
                row,
                self._latest_only_source(source),
            )
            if start_date <= revenue.revenue_date <= end_date:
                return [revenue]
        return []

    async def _fetch_official_openapi_valuation(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetric]:
        if not self.official_openapi_fallback_enabled:
            return []
        for endpoint, source, converter in (
            (
                self.TWSE_VALUATION_ENDPOINT,
                "TWSE OpenAPI BWIBBU_ALL",
                self._twse_openapi_row_to_valuation_metric,
            ),
            (
                self.TPEX_VALUATION_ENDPOINT,
                "TPEx OpenAPI tpex_mainboard_peratio_analysis",
                self._tpex_openapi_row_to_valuation_metric,
            ),
        ):
            row = self._find_official_row(await self._fetch_official_openapi_rows(endpoint), ticker)
            if not row:
                continue
            valuation = converter(row, ticker, self._latest_only_source(source))
            if start_date <= valuation.trade_date <= end_date:
                return [valuation]
        return []

    async def _fetch_official_openapi_financial_metrics(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[FinancialMetric]:
        if not self.official_openapi_fallback_enabled:
            return []
        income_row, income_source = await self._find_first_official_statement_row(
            ticker,
            [(self.TWSE_OPENAPI_BASE_URL, endpoint) for endpoint in self.TWSE_INCOME_STATEMENT_ENDPOINTS]
            + [(self.TPEX_OPENAPI_BASE_URL, endpoint) for endpoint in self.TPEX_INCOME_STATEMENT_ENDPOINTS],
        )
        balance_row, balance_source = await self._find_first_official_statement_row(
            ticker,
            [(self.TWSE_OPENAPI_BASE_URL, endpoint) for endpoint in self.TWSE_BALANCE_SHEET_ENDPOINTS]
            + [(self.TPEX_OPENAPI_BASE_URL, endpoint) for endpoint in self.TPEX_BALANCE_SHEET_ENDPOINTS],
        )
        metrics: list[FinancialMetric] = []
        if income_row:
            report_date = self._official_statement_report_date(income_row)
            if start_date <= report_date <= end_date:
                metrics.extend(
                    self._official_statement_metrics(
                        income_row,
                        report_date,
                        statement_type="income_statement",
                        metric_names=("營業收入", "本期淨利（淨損）", "淨利（淨損）歸屬於母公司業主", "基本每股盈餘（元）"),
                        source=self._latest_only_source(income_source),
                    )
                )
        if balance_row:
            report_date = self._official_statement_report_date(balance_row)
            if start_date <= report_date <= end_date:
                metrics.extend(
                    self._official_statement_metrics(
                        balance_row,
                        report_date,
                        statement_type="balance_sheet",
                        metric_names=("資產總額", "資產總計", "負債總額", "負債總計", "權益總額", "權益總計", "每股參考淨值"),
                        source=self._latest_only_source(balance_source),
                    )
                )
        return metrics

    @classmethod
    def _latest_only_source(cls, source: str) -> str:
        source = str(source or "").strip()
        if not source:
            return cls.LATEST_ONLY_SOURCE_MARKER
        if cls.LATEST_ONLY_SOURCE_MARKER in source.lower():
            return source
        return f"{source}; {cls.LATEST_ONLY_SOURCE_MARKER}"

    async def _find_first_official_statement_row(
        self,
        ticker: str,
        endpoints: list[tuple[str, str]],
    ) -> tuple[dict | None, str]:
        for base_url, endpoint in endpoints:
            rows = await self._fetch_official_openapi_rows(f"{base_url}/{endpoint}")
            row = self._find_official_row(rows, ticker)
            if row:
                source_prefix = "TWSE" if "twse.com.tw" in base_url else "TPEx"
                return row, f"{source_prefix} OpenAPI {endpoint.split('/')[-1]}"
        return None, ""

    async def _fetch_official_openapi_rows(self, url: str) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=self.official_openapi_timeout, follow_redirects=True) as client:
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _find_official_row(rows: list[dict], ticker: str) -> dict | None:
        ticker = str(ticker)
        for row in rows:
            code = row.get("Code") or row.get("公司代號") or row.get("SecuritiesCompanyCode")
            if str(code or "").strip() == ticker:
                return row
        return None

    def _provider_circuit_setting(self, provider: str, suffix: str, default):
        attr = f"{provider}_circuit_breaker_{suffix}"
        return getattr(self.settings, attr, default)

    def _provider_circuit_breaker(self, provider: str) -> ProviderCircuitBreaker:
        breaker = self._circuit_breakers[provider]
        breaker.configure(
            enabled=self._provider_circuit_setting(provider, "enabled", True),
            failure_threshold=self._provider_circuit_setting(provider, "failure_threshold", 5),
            recovery_seconds=self._provider_circuit_setting(provider, "recovery_seconds", 60.0),
        )
        return breaker

    def _before_provider_request(self, provider: str) -> None:
        self._provider_circuit_breaker(provider).before_call()

    def _record_provider_success(self, provider: str) -> None:
        self._provider_circuit_breaker(provider).record_success()

    def _record_provider_failure(self, provider: str) -> None:
        self._provider_circuit_breaker(provider).record_failure()

    def _should_retry_status(self, status_code: int, attempt: int) -> bool:
        return status_code in FINMIND_RETRYABLE_HTTP_STATUSES and attempt < self.finmind_max_retries

    def _should_retry_fugle_status(self, status_code: int, attempt: int) -> bool:
        return status_code in FUGLE_RETRYABLE_HTTP_STATUSES and attempt < self.fugle_max_retries

    async def _sleep_before_retry(self, response: httpx.Response | None, attempt: int) -> None:
        await asyncio.sleep(self._retry_delay_seconds(response, attempt))

    async def _sleep_before_fugle_retry(
        self,
        response: httpx.Response | None,
        attempt: int,
    ) -> None:
        await asyncio.sleep(self._fugle_retry_delay_seconds(response, attempt))

    def _retry_delay_seconds(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(self.finmind_max_retry_delay_seconds, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        return min(
            self.finmind_max_retry_delay_seconds,
            self.finmind_base_retry_delay_seconds * (2**attempt),
        )

    def _fugle_retry_delay_seconds(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(self.fugle_max_retry_delay_seconds, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        return min(
            self.fugle_max_retry_delay_seconds,
            self.fugle_base_retry_delay_seconds * (2**attempt),
        )

    def _market_price_provider_order(self) -> list[str]:
        providers = str(getattr(self.settings, "market_price_provider_order", "finmind,fugle"))
        normalized: list[str] = []
        for provider in providers.replace("\n", ",").split(","):
            provider = provider.strip().lower()
            if provider in {"finmind", "fugle", "official_openapi"} and provider not in normalized:
                normalized.append(provider)
        return normalized or ["finmind"]

    @property
    def finmind_max_retries(self) -> int:
        return max(0, int(getattr(self.settings, "finmind_max_retries", 2)))

    @property
    def finmind_base_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "finmind_base_retry_delay_seconds", 0.5)))

    @property
    def finmind_max_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "finmind_max_retry_delay_seconds", 5.0)))

    @property
    def finmind_public_fallback_enabled(self) -> bool:
        return bool(getattr(self.settings, "finmind_public_fallback_enabled", True))

    @property
    def fugle_api_key(self) -> str:
        return str(getattr(self.settings, "fugle_api_key", "") or "").strip()

    @property
    def fugle_max_retries(self) -> int:
        return max(0, int(getattr(self.settings, "fugle_max_retries", 2)))

    @property
    def fugle_base_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "fugle_base_retry_delay_seconds", 0.5)))

    @property
    def fugle_max_retry_delay_seconds(self) -> float:
        return max(0.0, float(getattr(self.settings, "fugle_max_retry_delay_seconds", 5.0)))

    @property
    def official_openapi_fallback_enabled(self) -> bool:
        return bool(getattr(self.settings, "market_official_openapi_fallback_enabled", True))

    @staticmethod
    def _row_to_snapshot(row: dict) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            trade_date=date.fromisoformat(row["date"]),
            open=MarketDataClient._float_or_none(row.get("open")),
            high=MarketDataClient._float_or_none(row.get("max")),
            low=MarketDataClient._float_or_none(row.get("min")),
            close=MarketDataClient._float_or_none(row.get("close")),
            spread=MarketDataClient._float_or_none(row.get("spread")),
            trading_volume=MarketDataClient._int_or_none(row.get("Trading_Volume")),
            trading_money=MarketDataClient._int_or_none(row.get("Trading_money")),
            trading_turnover=MarketDataClient._float_or_none(row.get("Trading_turnover")),
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _twse_openapi_row_to_snapshot(row: dict, ticker: str, source: str) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=str(row.get("Code") or ticker),
            trade_date=MarketDataClient._roc_date_to_date(row.get("Date")),
            open=MarketDataClient._float_or_none(row.get("OpeningPrice")),
            high=MarketDataClient._float_or_none(row.get("HighestPrice")),
            low=MarketDataClient._float_or_none(row.get("LowestPrice")),
            close=MarketDataClient._float_or_none(row.get("ClosingPrice")),
            spread=MarketDataClient._float_or_none(row.get("Change")),
            trading_volume=MarketDataClient._int_or_none(row.get("TradeVolume")),
            trading_money=MarketDataClient._int_or_none(row.get("TradeValue")),
            source=source,
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _tpex_openapi_row_to_snapshot(row: dict, ticker: str, source: str) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=str(row.get("SecuritiesCompanyCode") or ticker),
            trade_date=MarketDataClient._roc_date_to_date(row.get("Date")),
            open=MarketDataClient._float_or_none(row.get("Open")),
            high=MarketDataClient._float_or_none(row.get("High")),
            low=MarketDataClient._float_or_none(row.get("Low")),
            close=MarketDataClient._float_or_none(row.get("Close")),
            spread=MarketDataClient._float_or_none(row.get("Change")),
            trading_volume=MarketDataClient._int_or_none(row.get("TradingShares")),
            trading_money=MarketDataClient._int_or_none(row.get("TransactionAmount")),
            source=source,
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _fugle_row_to_snapshot(row: dict, ticker: str) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=str(row.get("symbol") or row.get("stock_id") or row.get("data_id") or ticker),
            trade_date=date.fromisoformat(row["date"]),
            open=MarketDataClient._float_or_none(row.get("open")),
            high=MarketDataClient._float_or_none(row.get("high")),
            low=MarketDataClient._float_or_none(row.get("low")),
            close=MarketDataClient._float_or_none(row.get("close")),
            spread=MarketDataClient._float_or_none(row.get("change") or row.get("spread")),
            trading_volume=MarketDataClient._int_or_none(row.get("volume")),
            trading_money=MarketDataClient._int_or_none(row.get("turnover")),
            source="Fugle historical candles",
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _fugle_stats_row_to_snapshot(row: dict, ticker: str) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=str(row.get("symbol") or ticker),
            trade_date=date.fromisoformat(row["date"]),
            open=MarketDataClient._float_or_none(row.get("openPrice")),
            high=MarketDataClient._float_or_none(row.get("highPrice")),
            low=MarketDataClient._float_or_none(row.get("lowPrice")),
            close=MarketDataClient._float_or_none(row.get("closePrice")),
            spread=MarketDataClient._float_or_none(row.get("change")),
            trading_volume=MarketDataClient._int_or_none(row.get("tradeVolume")),
            trading_money=MarketDataClient._int_or_none(row.get("tradeValue")),
            source="Fugle historical stats",
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _row_to_monthly_revenue(row: dict) -> MonthlyRevenue:
        revenue_date = date.fromisoformat(row["date"])
        return MonthlyRevenue(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            revenue_date=revenue_date,
            revenue=MarketDataClient._int_or_none(row.get("revenue")) or 0,
            revenue_year=int(row.get("revenue_year") or revenue_date.year),
            revenue_month=int(row.get("revenue_month") or revenue_date.month),
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _official_openapi_row_to_monthly_revenue(row: dict, source: str) -> MonthlyRevenue:
        revenue_year_month = str(row.get("資料年月") or "")
        if len(revenue_year_month) < 5:
            revenue_date = MarketDataClient._roc_date_to_date(row.get("出表日期"))
            revenue_year = revenue_date.year
            revenue_month = revenue_date.month
        else:
            revenue_year = MarketDataClient._roc_year_to_ad(int(revenue_year_month[:-2]))
            revenue_month = int(revenue_year_month[-2:])
            revenue_date = date(
                revenue_year,
                revenue_month,
                monthrange(revenue_year, revenue_month)[1],
            )
        return MonthlyRevenue(
            ticker=str(row.get("公司代號")),
            revenue_date=revenue_date,
            revenue=MarketDataClient._int_or_none(row.get("營業收入-當月營收")) or 0,
            revenue_year=revenue_year,
            revenue_month=revenue_month,
            yoy_pct=MarketDataClient._float_or_none(row.get("營業收入-去年同月增減(%)")),
            source=source,
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _row_to_financial_metric(row: dict, statement_type: str, source: str) -> FinancialMetric:
        return FinancialMetric(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            report_date=date.fromisoformat(row["date"]),
            statement_type=statement_type,
            metric=str(row.get("type") or row.get("metric") or row.get("origin_name")),
            value=float(row.get("value")),
            origin_name=row.get("origin_name"),
            source=f"FinMind {source}",
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _official_statement_metrics(
        row: dict,
        report_date: date,
        *,
        statement_type: str,
        metric_names: tuple[str, ...],
        source: str,
    ) -> list[FinancialMetric]:
        ticker = str(row.get("公司代號") or row.get("SecuritiesCompanyCode"))
        metrics: list[FinancialMetric] = []
        for metric_name in metric_names:
            value = MarketDataClient._float_or_none(row.get(metric_name))
            if value is None:
                continue
            metrics.append(
                FinancialMetric(
                    ticker=ticker,
                    report_date=report_date,
                    statement_type=statement_type,
                    metric=metric_name,
                    value=value,
                    origin_name=metric_name,
                    source=source,
                    fetched_at=utc_now_naive(),
                )
            )
        return metrics

    @staticmethod
    def _row_to_valuation_metric(row: dict) -> ValuationMetric:
        return ValuationMetric(
            ticker=str(row.get("stock_id") or row.get("data_id")),
            trade_date=date.fromisoformat(row["date"]),
            pe_ratio=MarketDataClient._float_or_none(
                row.get("PER") or row.get("pe_ratio") or row.get("PE")
            ),
            pb_ratio=MarketDataClient._float_or_none(
                row.get("PBR") or row.get("pb_ratio") or row.get("PB")
            ),
            dividend_yield=MarketDataClient._float_or_none(
                row.get("dividend_yield") or row.get("DividendYield")
            ),
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _twse_openapi_row_to_valuation_metric(row: dict, ticker: str, source: str) -> ValuationMetric:
        return ValuationMetric(
            ticker=str(row.get("Code") or ticker),
            trade_date=MarketDataClient._roc_date_to_date(row.get("Date")),
            pe_ratio=MarketDataClient._float_or_none(row.get("PEratio")),
            pb_ratio=MarketDataClient._float_or_none(row.get("PBratio")),
            dividend_yield=MarketDataClient._float_or_none(row.get("DividendYield")),
            source=source,
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _tpex_openapi_row_to_valuation_metric(row: dict, ticker: str, source: str) -> ValuationMetric:
        return ValuationMetric(
            ticker=str(row.get("SecuritiesCompanyCode") or ticker),
            trade_date=MarketDataClient._roc_date_to_date(row.get("Date")),
            pe_ratio=MarketDataClient._float_or_none(row.get("PriceEarningRatio")),
            pb_ratio=MarketDataClient._float_or_none(row.get("PriceBookRatio")),
            dividend_yield=MarketDataClient._float_or_none(row.get("YieldRatio")),
            source=source,
            fetched_at=utc_now_naive(),
        )

    @staticmethod
    def _official_statement_report_date(row: dict) -> date:
        year = int(row.get("年度") or row.get("Year"))
        season = int(row.get("季別") or row.get("Season"))
        ad_year = MarketDataClient._roc_year_to_ad(year)
        quarter_end_month = min(12, max(1, season * 3))
        return date(ad_year, quarter_end_month, monthrange(ad_year, quarter_end_month)[1])

    @staticmethod
    def _roc_date_to_date(value) -> date:
        raw = str(value or "").strip()
        if len(raw) != 7 or not raw.isdigit():
            return date.fromisoformat(raw)
        year = MarketDataClient._roc_year_to_ad(int(raw[:3]))
        return date(year, int(raw[3:5]), int(raw[5:7]))

    @staticmethod
    def _roc_year_to_ad(year: int) -> int:
        return year + 1911 if year < 1_000 else year

    @staticmethod
    def _float_or_none(value) -> float | None:
        if value in (None, "", "-", "--"):
            return None
        return float(str(value).replace(",", "").replace("+", ""))

    @staticmethod
    def _int_or_none(value) -> int | None:
        if value in (None, "", "-", "--"):
            return None
        return int(float(str(value).replace(",", "").replace("+", "")))
