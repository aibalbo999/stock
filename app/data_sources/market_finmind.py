from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import httpx

from app.data_sources import market_provider_runtime

FINMIND_DATA_URL = "https://api.finmindtrade.com/api/v4/data"


async def fetch_finmind_rows(
    *,
    settings: Any,
    timeout: httpx.Timeout,
    circuit_breakers: dict[str, market_provider_runtime.ProviderCircuitBreaker],
    dataset: str,
    ticker: str,
    start_date: date,
    end_date: date,
    max_retries: int,
    public_fallback_enabled: bool,
    sleep_before_retry: Callable[[httpx.Response | None, int], Awaitable[None]],
) -> list[dict]:
    finmind_token = getattr(settings, "finmind_token", None)
    if not finmind_token and not public_fallback_enabled:
        raise market_provider_runtime.MarketDataProviderUnavailable(
            "FinMind token is not configured and public fallback is disabled"
        )

    breaker = market_provider_runtime.configure_provider_circuit_breaker(
        settings,
        circuit_breakers,
        "finmind",
    )
    breaker.before_call()

    params = {
        "dataset": dataset,
        "data_id": ticker,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    headers = {}
    if finmind_token:
        headers["Authorization"] = f"Bearer {finmind_token}"

    last_error: Exception | None = None
    for attempt in range(max(0, int(max_retries)) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    FINMIND_DATA_URL,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
            market_provider_runtime.configure_provider_circuit_breaker(
                settings,
                circuit_breakers,
                "finmind",
            ).record_success()
            return response.json().get("data", [])
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if not market_provider_runtime.should_retry_status(
                exc.response.status_code,
                attempt,
                retryable_statuses=market_provider_runtime.FINMIND_RETRYABLE_HTTP_STATUSES,
                max_retries=max_retries,
            ):
                if exc.response.status_code in market_provider_runtime.FINMIND_RETRYABLE_HTTP_STATUSES:
                    market_provider_runtime.configure_provider_circuit_breaker(
                        settings,
                        circuit_breakers,
                        "finmind",
                    ).record_failure()
                raise
            await sleep_before_retry(exc.response, attempt)
        except (httpx.TransportError, TimeoutError) as exc:
            last_error = exc
            if attempt >= max(0, int(max_retries)):
                market_provider_runtime.configure_provider_circuit_breaker(
                    settings,
                    circuit_breakers,
                    "finmind",
                ).record_failure()
                raise
            await sleep_before_retry(None, attempt)
    if last_error:
        raise last_error
    return []
