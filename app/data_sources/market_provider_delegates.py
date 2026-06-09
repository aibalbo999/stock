from __future__ import annotations

import asyncio
from datetime import date

import httpx

from app.data_sources import (
    market_client_runtime,
    market_finmind,
    market_fugle,
    market_official_fallbacks,
    market_official_openapi,
    market_provider_runtime,
)
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric


FINMIND_RETRYABLE_HTTP_STATUSES = market_provider_runtime.FINMIND_RETRYABLE_HTTP_STATUSES
FUGLE_RETRYABLE_HTTP_STATUSES = market_provider_runtime.FUGLE_RETRYABLE_HTTP_STATUSES
MarketDataProviderUnavailable = market_provider_runtime.MarketDataProviderUnavailable
ProviderCircuitBreaker = market_provider_runtime.ProviderCircuitBreaker


class MarketProviderDelegateMixin:
    LATEST_ONLY_SOURCE_MARKER: str
    settings: object
    timeout: httpx.Timeout
    fugle_timeout: httpx.Timeout
    official_openapi_timeout: httpx.Timeout
    _circuit_breakers: dict[str, ProviderCircuitBreaker]

    async def _fetch_finmind_rows(
        self,
        dataset: str,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        return await market_finmind.fetch_finmind_rows(
            settings=self.settings,
            timeout=self.timeout,
            circuit_breakers=self._circuit_breakers,
            dataset=dataset,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            max_retries=self.finmind_max_retries,
            public_fallback_enabled=self.finmind_public_fallback_enabled,
            sleep_before_retry=self._sleep_before_retry,
        )

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
                    snapshots = await market_finmind.fetch_price_history(
                        ticker=ticker,
                        start_date=start_date,
                        end_date=end_date,
                        fetch_rows=self._fetch_finmind_rows,
                    )
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
        return await market_fugle.fetch_price_history(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            api_key=self.fugle_api_key,
            fetch_json=lambda url, params: self._fetch_fugle_json(url, params=params),
        )

    async def _fetch_fugle_historical_candle_rows(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        return await market_fugle.fetch_historical_candle_rows(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            api_key=self.fugle_api_key,
            fetch_json=lambda url, params: self._fetch_fugle_json(url, params=params),
        )

    async def _fetch_fugle_historical_stats_row(self, ticker: str) -> dict:
        return await market_fugle.fetch_historical_stats_row(
            ticker=ticker,
            api_key=self.fugle_api_key,
            fetch_json=lambda url, params: self._fetch_fugle_json(url, params=params),
        )

    async def _fetch_fugle_json(self, url: str, *, params: dict) -> dict:
        return await market_fugle.fetch_fugle_json(
            settings=self.settings,
            timeout=self.fugle_timeout,
            circuit_breakers=self._circuit_breakers,
            url=url,
            params=params,
            api_key=self.fugle_api_key,
            max_retries=self.fugle_max_retries,
            sleep_before_retry=self._sleep_before_fugle_retry,
        )

    async def _fetch_official_openapi_price_snapshot(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketSnapshot]:
        return await market_official_fallbacks.fetch_price_snapshot(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            fallback_enabled=self.official_openapi_fallback_enabled,
            fetch_rows=self._fetch_official_openapi_rows,
        )

    async def _fetch_official_openapi_monthly_revenue(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue]:
        return await market_official_fallbacks.fetch_monthly_revenue(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            fallback_enabled=self.official_openapi_fallback_enabled,
            fetch_rows=self._fetch_official_openapi_rows,
        )

    async def _fetch_official_openapi_valuation(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetric]:
        return await market_official_fallbacks.fetch_valuation(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            fallback_enabled=self.official_openapi_fallback_enabled,
            fetch_rows=self._fetch_official_openapi_rows,
        )

    async def _fetch_official_openapi_financial_metrics(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[FinancialMetric]:
        return await market_official_fallbacks.fetch_financial_metrics(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            fallback_enabled=self.official_openapi_fallback_enabled,
            fetch_rows=self._fetch_official_openapi_rows,
        )

    @classmethod
    def _latest_only_source(cls, source: str) -> str:
        return market_official_fallbacks.latest_only_source(
            source,
            marker=cls.LATEST_ONLY_SOURCE_MARKER,
        )

    async def _find_first_official_statement_row(
        self,
        ticker: str,
        endpoints: list[tuple[str, str]],
    ) -> tuple[dict | None, str]:
        return await market_official_openapi.find_first_statement_row(
            ticker=ticker,
            endpoints=endpoints,
            fetch_rows=self._fetch_official_openapi_rows,
        )

    async def _fetch_official_openapi_rows(self, url: str) -> list[dict]:
        return await market_official_openapi.fetch_official_openapi_rows(
            url,
            timeout=self.official_openapi_timeout,
        )

    @staticmethod
    def _find_official_row(rows: list[dict], ticker: str) -> dict | None:
        return market_official_openapi.find_official_row(rows, ticker)

    def _provider_circuit_setting(self, provider: str, suffix: str, default):
        return market_client_runtime.provider_circuit_setting(
            self.settings,
            provider,
            suffix,
            default,
        )

    def _provider_circuit_breaker(self, provider: str) -> ProviderCircuitBreaker:
        return market_provider_runtime.configure_provider_circuit_breaker(
            self.settings,
            self._circuit_breakers,
            provider,
        )

    def _before_provider_request(self, provider: str) -> None:
        self._provider_circuit_breaker(provider).before_call()

    def _record_provider_success(self, provider: str) -> None:
        self._provider_circuit_breaker(provider).record_success()

    def _record_provider_failure(self, provider: str) -> None:
        self._provider_circuit_breaker(provider).record_failure()

    def _should_retry_status(self, status_code: int, attempt: int) -> bool:
        return market_provider_runtime.should_retry_status(
            status_code,
            attempt,
            retryable_statuses=FINMIND_RETRYABLE_HTTP_STATUSES,
            max_retries=self.finmind_max_retries,
        )

    def _should_retry_fugle_status(self, status_code: int, attempt: int) -> bool:
        return market_provider_runtime.should_retry_status(
            status_code,
            attempt,
            retryable_statuses=FUGLE_RETRYABLE_HTTP_STATUSES,
            max_retries=self.fugle_max_retries,
        )

    async def _sleep_before_retry(self, response: httpx.Response | None, attempt: int) -> None:
        await asyncio.sleep(self._retry_delay_seconds(response, attempt))

    async def _sleep_before_fugle_retry(
        self,
        response: httpx.Response | None,
        attempt: int,
    ) -> None:
        await asyncio.sleep(self._fugle_retry_delay_seconds(response, attempt))

    def _retry_delay_seconds(self, response: httpx.Response | None, attempt: int) -> float:
        return market_provider_runtime.retry_delay_seconds(
            response,
            attempt,
            base_retry_delay_seconds=self.finmind_base_retry_delay_seconds,
            max_retry_delay_seconds=self.finmind_max_retry_delay_seconds,
        )

    def _fugle_retry_delay_seconds(self, response: httpx.Response | None, attempt: int) -> float:
        return market_provider_runtime.retry_delay_seconds(
            response,
            attempt,
            base_retry_delay_seconds=self.fugle_base_retry_delay_seconds,
            max_retry_delay_seconds=self.fugle_max_retry_delay_seconds,
        )

    def _market_price_provider_order(self) -> list[str]:
        return market_client_runtime.market_price_provider_order(self.settings)

    @property
    def finmind_max_retries(self) -> int:
        return market_client_runtime.finmind_max_retries(self.settings)

    @property
    def finmind_base_retry_delay_seconds(self) -> float:
        return market_client_runtime.finmind_base_retry_delay_seconds(self.settings)

    @property
    def finmind_max_retry_delay_seconds(self) -> float:
        return market_client_runtime.finmind_max_retry_delay_seconds(self.settings)

    @property
    def finmind_public_fallback_enabled(self) -> bool:
        return market_client_runtime.finmind_public_fallback_enabled(self.settings)

    @property
    def fugle_api_key(self) -> str:
        return market_client_runtime.fugle_api_key(self.settings)

    @property
    def fugle_max_retries(self) -> int:
        return market_client_runtime.fugle_max_retries(self.settings)

    @property
    def fugle_base_retry_delay_seconds(self) -> float:
        return market_client_runtime.fugle_base_retry_delay_seconds(self.settings)

    @property
    def fugle_max_retry_delay_seconds(self) -> float:
        return market_client_runtime.fugle_max_retry_delay_seconds(self.settings)

    @property
    def official_openapi_fallback_enabled(self) -> bool:
        return market_client_runtime.official_openapi_fallback_enabled(self.settings)
