from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date

from app.data_sources import market_official_openapi, market_parsers
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric

LATEST_ONLY_SOURCE_MARKER = "latest-only"
INCOME_STATEMENT_METRIC_NAMES = (
    "營業收入",
    "本期淨利（淨損）",
    "淨利（淨損）歸屬於母公司業主",
    "基本每股盈餘（元）",
)
BALANCE_SHEET_METRIC_NAMES = (
    "資產總額",
    "資產總計",
    "負債總額",
    "負債總計",
    "權益總額",
    "權益總計",
    "每股參考淨值",
)

FetchOfficialRows = Callable[[str], Awaitable[list[dict]]]


def latest_only_source(source: str, *, marker: str = LATEST_ONLY_SOURCE_MARKER) -> str:
    source = str(source or "").strip()
    if not source:
        return marker
    if marker in source.lower():
        return source
    return f"{source}; {marker}"


async def fetch_price_snapshot(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fallback_enabled: bool,
    fetch_rows: FetchOfficialRows,
) -> list[MarketSnapshot]:
    if not fallback_enabled:
        return []
    for endpoint, source, converter in (
        (
            market_official_openapi.TWSE_PRICE_ENDPOINT,
            "TWSE OpenAPI STOCK_DAY_ALL",
            market_parsers.twse_openapi_row_to_snapshot,
        ),
        (
            market_official_openapi.TPEX_PRICE_ENDPOINT,
            "TPEx OpenAPI tpex_mainboard_quotes",
            market_parsers.tpex_openapi_row_to_snapshot,
        ),
    ):
        row = market_official_openapi.find_official_row(await fetch_rows(endpoint), ticker)
        if not row:
            continue
        snapshot = converter(row, ticker, latest_only_source(source))
        if start_date <= snapshot.trade_date <= end_date:
            return [snapshot]
    return []


async def fetch_monthly_revenue(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fallback_enabled: bool,
    fetch_rows: FetchOfficialRows,
) -> list[MonthlyRevenue]:
    if not fallback_enabled:
        return []
    for endpoint, source in (
        (market_official_openapi.TWSE_MONTHLY_REVENUE_ENDPOINT, "TWSE OpenAPI t187ap05_L"),
        (market_official_openapi.TPEX_MONTHLY_REVENUE_ENDPOINT, "TPEx OpenAPI mopsfin_t187ap05_O"),
    ):
        row = market_official_openapi.find_official_row(await fetch_rows(endpoint), ticker)
        if not row:
            continue
        revenue = market_parsers.official_openapi_row_to_monthly_revenue(
            row,
            latest_only_source(source),
        )
        if start_date <= revenue.revenue_date <= end_date:
            return [revenue]
    return []


async def fetch_valuation(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fallback_enabled: bool,
    fetch_rows: FetchOfficialRows,
) -> list[ValuationMetric]:
    if not fallback_enabled:
        return []
    for endpoint, source, converter in (
        (
            market_official_openapi.TWSE_VALUATION_ENDPOINT,
            "TWSE OpenAPI BWIBBU_ALL",
            market_parsers.twse_openapi_row_to_valuation_metric,
        ),
        (
            market_official_openapi.TPEX_VALUATION_ENDPOINT,
            "TPEx OpenAPI tpex_mainboard_peratio_analysis",
            market_parsers.tpex_openapi_row_to_valuation_metric,
        ),
    ):
        row = market_official_openapi.find_official_row(await fetch_rows(endpoint), ticker)
        if not row:
            continue
        valuation = converter(row, ticker, latest_only_source(source))
        if start_date <= valuation.trade_date <= end_date:
            return [valuation]
    return []


async def fetch_financial_metrics(
    *,
    ticker: str,
    start_date: date,
    end_date: date,
    fallback_enabled: bool,
    fetch_rows: FetchOfficialRows,
) -> list[FinancialMetric]:
    if not fallback_enabled:
        return []
    income_row, income_source = await market_official_openapi.find_first_statement_row(
        ticker=ticker,
        endpoints=_income_statement_endpoint_pairs(),
        fetch_rows=fetch_rows,
    )
    balance_row, balance_source = await market_official_openapi.find_first_statement_row(
        ticker=ticker,
        endpoints=_balance_sheet_endpoint_pairs(),
        fetch_rows=fetch_rows,
    )

    metrics: list[FinancialMetric] = []
    if income_row:
        report_date = market_parsers.official_statement_report_date(income_row)
        if start_date <= report_date <= end_date:
            metrics.extend(
                market_parsers.official_statement_metrics(
                    income_row,
                    report_date,
                    statement_type="income_statement",
                    metric_names=INCOME_STATEMENT_METRIC_NAMES,
                    source=latest_only_source(income_source),
                )
            )
    if balance_row:
        report_date = market_parsers.official_statement_report_date(balance_row)
        if start_date <= report_date <= end_date:
            metrics.extend(
                market_parsers.official_statement_metrics(
                    balance_row,
                    report_date,
                    statement_type="balance_sheet",
                    metric_names=BALANCE_SHEET_METRIC_NAMES,
                    source=latest_only_source(balance_source),
                )
            )
    return metrics


def _income_statement_endpoint_pairs() -> list[tuple[str, str]]:
    return [
        (market_official_openapi.TWSE_OPENAPI_BASE_URL, endpoint)
        for endpoint in market_official_openapi.TWSE_INCOME_STATEMENT_ENDPOINTS
    ] + [
        (market_official_openapi.TPEX_OPENAPI_BASE_URL, endpoint)
        for endpoint in market_official_openapi.TPEX_INCOME_STATEMENT_ENDPOINTS
    ]


def _balance_sheet_endpoint_pairs() -> list[tuple[str, str]]:
    return [
        (market_official_openapi.TWSE_OPENAPI_BASE_URL, endpoint)
        for endpoint in market_official_openapi.TWSE_BALANCE_SHEET_ENDPOINTS
    ] + [
        (market_official_openapi.TPEX_OPENAPI_BASE_URL, endpoint)
        for endpoint in market_official_openapi.TPEX_BALANCE_SHEET_ENDPOINTS
    ]
