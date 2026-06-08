from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import httpx

from app.data_sources import market_provider_runtime
from app.data_sources import market_parsers
from app.models.schemas import MarketSnapshot

FUGLE_HISTORICAL_CANDLES_URL = (
    "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{ticker}"
)
FUGLE_HISTORICAL_STATS_URL = "https://api.fugle.tw/marketdata/v1.0/stock/historical/stats/{ticker}"


async def fetch_price_history(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    api_key: str,
    fetch_json: Callable[[str, dict], Awaitable[dict]],
) -> list[MarketSnapshot]:
    candle_error: Exception | None = None
    try:
        rows = await fetch_historical_candle_rows(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            fetch_json=fetch_json,
        )
        snapshots = [market_parsers.fugle_row_to_snapshot(row, ticker) for row in rows]
        if snapshots:
            return snapshots
    except Exception as exc:
        candle_error = exc

    try:
        row = await fetch_historical_stats_row(
            ticker=ticker,
            api_key=api_key,
            fetch_json=fetch_json,
        )
        if row:
            snapshot = market_parsers.fugle_stats_row_to_snapshot(row, ticker)
            if start_date <= snapshot.trade_date <= end_date:
                return [snapshot]
    except Exception as stats_error:
        if candle_error is not None:
            raise candle_error from stats_error
        raise

    if candle_error is not None:
        raise candle_error
    return []


async def fetch_historical_candle_rows(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    api_key: str,
    fetch_json: Callable[[str, dict], Awaitable[dict]],
) -> list[dict]:
    if not api_key:
        raise market_provider_runtime.MarketDataProviderUnavailable("Fugle API key is not configured")

    params = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "timeframe": "D",
        "fields": "open,high,low,close,volume,turnover,change",
        "sort": "asc",
    }
    payload = await fetch_json(FUGLE_HISTORICAL_CANDLES_URL.format(ticker=ticker), params)
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(data, dict):
        data = data.get("candles", [])
    return data if isinstance(data, list) else []


async def fetch_historical_stats_row(
    *,
    ticker: str,
    api_key: str,
    fetch_json: Callable[[str, dict], Awaitable[dict]],
) -> dict:
    if not api_key:
        raise market_provider_runtime.MarketDataProviderUnavailable("Fugle API key is not configured")

    payload = await fetch_json(
        FUGLE_HISTORICAL_STATS_URL.format(ticker=ticker),
        {},
    )
    return payload if isinstance(payload, dict) else {}


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
