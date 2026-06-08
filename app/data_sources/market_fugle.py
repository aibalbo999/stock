from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.data_sources import market_provider_runtime

FUGLE_HISTORICAL_CANDLES_URL = (
    "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{ticker}"
)
FUGLE_HISTORICAL_STATS_URL = "https://api.fugle.tw/marketdata/v1.0/stock/historical/stats/{ticker}"


async def fetch_fugle_json(
    *,
    settings: Any,
    timeout: httpx.Timeout,
    circuit_breakers: dict[str, market_provider_runtime.ProviderCircuitBreaker],
    url: str,
    params: dict,
    api_key: str,
    max_retries: int,
    sleep_before_retry: Callable[[httpx.Response | None, int], Awaitable[None]],
) -> dict:
    headers = {"X-API-KEY": api_key}
    breaker = market_provider_runtime.configure_provider_circuit_breaker(
        settings,
        circuit_breakers,
        "fugle",
    )
    breaker.before_call()

    last_error: Exception | None = None
    for attempt in range(max(0, int(max_retries)) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            market_provider_runtime.configure_provider_circuit_breaker(
                settings,
                circuit_breakers,
                "fugle",
            ).record_success()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if not market_provider_runtime.should_retry_status(
                exc.response.status_code,
                attempt,
                retryable_statuses=market_provider_runtime.FUGLE_RETRYABLE_HTTP_STATUSES,
                max_retries=max_retries,
            ):
                if exc.response.status_code in market_provider_runtime.FUGLE_RETRYABLE_HTTP_STATUSES:
                    market_provider_runtime.configure_provider_circuit_breaker(
                        settings,
                        circuit_breakers,
                        "fugle",
                    ).record_failure()
                raise
            await sleep_before_retry(exc.response, attempt)
        except (httpx.TransportError, TimeoutError) as exc:
            last_error = exc
            if attempt >= max(0, int(max_retries)):
                market_provider_runtime.configure_provider_circuit_breaker(
                    settings,
                    circuit_breakers,
                    "fugle",
                ).record_failure()
                raise
            await sleep_before_retry(None, attempt)
    if last_error:
        raise last_error
    return {}
