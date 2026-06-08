from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

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
OFFICIAL_OPENAPI_USER_AGENT = "Mozilla/5.0"


async def fetch_official_openapi_rows(url: str, *, timeout: httpx.Timeout) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": OFFICIAL_OPENAPI_USER_AGENT})
            response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def find_official_row(rows: list[dict], ticker: str) -> dict | None:
    ticker = str(ticker)
    for row in rows:
        code = row.get("Code") or row.get("公司代號") or row.get("SecuritiesCompanyCode")
        if str(code or "").strip() == ticker:
            return row
    return None


async def find_first_statement_row(
    *,
    ticker: str,
    endpoints: list[tuple[str, str]],
    fetch_rows: Callable[[str], Awaitable[list[dict]]],
) -> tuple[dict | None, str]:
    for base_url, endpoint in endpoints:
        rows = await fetch_rows(f"{base_url}/{endpoint}")
        row = find_official_row(rows, ticker)
        if row:
            return row, official_statement_source(base_url, endpoint)
    return None, ""


def official_statement_source(base_url: str, endpoint: str) -> str:
    source_prefix = "TWSE" if "twse.com.tw" in base_url else "TPEx"
    return f"{source_prefix} OpenAPI {endpoint.split('/')[-1]}"
