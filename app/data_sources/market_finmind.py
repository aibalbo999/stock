from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import httpx

from app.data_sources import market_parsers, market_provider_runtime
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric

FINMIND_DATA_URL = "https://api.finmindtrade.com/api/v4/data"
PRICE_DATASET = "TaiwanStockPrice"
MONTHLY_REVENUE_DATASET = "TaiwanStockMonthRevenue"
VALUATION_DATASET = "TaiwanStockPER"
FINANCIAL_DATASETS = {
    "TaiwanStockFinancialStatements": "income_statement",
    "TaiwanStockBalanceSheet": "balance_sheet",
    "TaiwanStockCashFlowsStatement": "cash_flow",
}

FetchFinmindRows = Callable[[str, str, date, date], Awaitable[list[dict]]]


async def fetch_price_history(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fetch_rows: FetchFinmindRows,
) -> list[MarketSnapshot]:
    rows = await fetch_rows(PRICE_DATASET, ticker, start_date, end_date)
    return [market_parsers.row_to_snapshot(row) for row in rows]


async def fetch_monthly_revenue(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fetch_rows: FetchFinmindRows,
) -> list[MonthlyRevenue]:
    rows = await fetch_rows(MONTHLY_REVENUE_DATASET, ticker, start_date, end_date)
    return [market_parsers.row_to_monthly_revenue(row) for row in rows]


async def fetch_financial_metrics(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fetch_rows: FetchFinmindRows,
) -> list[FinancialMetric]:
    metrics: list[FinancialMetric] = []
    for dataset, statement_type in FINANCIAL_DATASETS.items():
        rows = await fetch_rows(dataset, ticker, start_date, end_date)
        metrics.extend(
            market_parsers.row_to_financial_metric(row, statement_type, dataset)
            for row in rows
            if market_parsers.float_or_none(row.get("value")) is not None
        )
    return metrics


async def fetch_valuation(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fetch_rows: FetchFinmindRows,
) -> list[ValuationMetric]:
    rows = await fetch_rows(VALUATION_DATASET, ticker, start_date, end_date)
    return [market_parsers.row_to_valuation_metric(row) for row in rows]


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
