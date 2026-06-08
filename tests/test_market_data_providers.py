import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.data_sources import (
    market_batch,
    market_cache_rescue,
    market_finmind,
    market_fugle,
    market_official_fallbacks,
    market_official_openapi,
    market_parsers,
    market_provider_runtime,
)
from app.data_sources.market import MarketDataClient, MarketDataProviderUnavailable
from app.models.schemas import ValuationMetric


def comparable_market_model(model):
    return model.model_dump(exclude={"fetched_at"})


def test_finmind_row_to_snapshot() -> None:
    row = {
        "date": "2026-05-22",
        "stock_id": "2330",
        "Trading_Volume": 123,
        "Trading_money": 456,
        "open": 1000.0,
        "max": 1010.0,
        "min": 990.0,
        "close": 1005.0,
        "spread": 5.0,
        "Trading_turnover": 789,
    }
    snapshot = MarketDataClient._row_to_snapshot(row)
    helper_snapshot = market_parsers.row_to_snapshot(row)

    assert snapshot.ticker == "2330"
    assert snapshot.trade_date == date(2026, 5, 22)
    assert snapshot.high == 1010.0
    assert snapshot.trading_volume == 123
    assert comparable_market_model(helper_snapshot) == comparable_market_model(snapshot)


def test_finmind_public_fallback_can_be_disabled_without_token() -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(finmind_token=None, finmind_public_fallback_enabled=False)

    with pytest.raises(MarketDataProviderUnavailable, match="public fallback is disabled"):
        asyncio.run(client._fetch_finmind_rows("TaiwanStockPrice", "2330", date(2026, 5, 1), date(2026, 5, 31)))


def test_finmind_provider_logic_lives_outside_client() -> None:
    client_source = Path("app/data_sources/market.py").read_text()
    finmind_source = Path("app/data_sources/market_finmind.py").read_text()

    assert market_finmind.FINMIND_DATA_URL == "https://api.finmindtrade.com/api/v4/data"
    assert "market_finmind.fetch_finmind_rows" in client_source
    assert "market_finmind.fetch_price_history" in client_source
    assert "market_finmind.fetch_financial_metrics" in client_source
    assert "FINMIND_DATA_URL" in finmind_source
    assert "FINANCIAL_DATASETS" in finmind_source
    assert "client.get(" not in client_source.split("async def _fetch_finmind_rows(", maxsplit=1)[1].split(
        "async def _fetch_price_history_uncached(",
        maxsplit=1,
    )[0]
    assert "TaiwanStockFinancialStatements" not in client_source.split(
        "async def get_financial_metrics_history(",
        maxsplit=1,
    )[1].split("async def get_financial_metrics_histories_with_errors(", maxsplit=1)[0]


def test_market_price_provider_order_logic_lives_outside_client() -> None:
    raw_order = " finmind\nfugle,finmind,official_openapi,unknown "
    client = MarketDataClient()
    client.settings = SimpleNamespace(market_price_provider_order=raw_order)

    provider_order = client._market_price_provider_order()
    helper_provider_order = market_provider_runtime.market_price_provider_order(raw_order)

    assert provider_order == ["finmind", "fugle", "official_openapi"]
    assert helper_provider_order == provider_order


def test_official_openapi_provider_logic_lives_outside_client() -> None:
    client_source = Path("app/data_sources/market.py").read_text()
    official_source = Path("app/data_sources/market_official_openapi.py").read_text()

    assert market_official_openapi.TWSE_PRICE_ENDPOINT == "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    assert market_official_openapi.TPEX_PRICE_ENDPOINT == "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    assert "market_official_openapi.fetch_official_openapi_rows" in client_source
    assert "market_official_openapi.find_first_statement_row" in client_source
    assert "OFFICIAL_OPENAPI_USER_AGENT" in official_source
    assert "client.get(" not in client_source.split(
        "async def _fetch_official_openapi_rows(",
        maxsplit=1,
    )[1].split("@staticmethod", maxsplit=1)[0]


def test_official_openapi_fallback_logic_lives_outside_client() -> None:
    client_source = Path("app/data_sources/market.py").read_text()
    fallback_source = Path("app/data_sources/market_official_fallbacks.py").read_text()

    assert market_official_fallbacks.latest_only_source("TWSE OpenAPI STOCK_DAY_ALL").endswith(
        "; latest-only"
    )
    assert "market_official_fallbacks.fetch_price_snapshot" in client_source
    assert "market_official_fallbacks.fetch_financial_metrics" in client_source
    assert "INCOME_STATEMENT_METRIC_NAMES" in fallback_source
    assert "TWSE OpenAPI STOCK_DAY_ALL" not in client_source.split(
        "async def _fetch_official_openapi_price_snapshot(",
        maxsplit=1,
    )[1].split("async def _fetch_official_openapi_monthly_revenue(", maxsplit=1)[0]


def test_market_cache_rescue_logic_lives_outside_client() -> None:
    client_source = Path("app/data_sources/market.py").read_text()
    helper_source = Path("app/data_sources/market_cache_rescue.py").read_text()

    assert MarketDataClient.STALE_CACHE_SOURCE_MARKER == market_cache_rescue.STALE_CACHE_SOURCE_MARKER
    assert "market_cache_rescue.get_or_fetch_with_rescue" in client_source
    assert "def get_or_fetch_with_rescue(" in helper_source
    assert "def mark_stale_cache_source(" in helper_source
    assert "except Exception" not in client_source.split(
        "async def get_financial_metrics_history(",
        maxsplit=1,
    )[1].split("async def get_financial_metrics_histories_with_errors(", maxsplit=1)[0]


def test_market_batch_orchestration_lives_outside_client() -> None:
    client_source = Path("app/data_sources/market.py").read_text()
    helper_source = Path("app/data_sources/market_batch.py").read_text()

    assert market_batch.TickerRows(ticker="2330", rows=[]).ticker == "2330"
    assert "market_batch.fetch_ticker_rows" in client_source
    assert "asyncio.gather" not in client_source
    assert "asyncio.Semaphore" not in client_source
    assert "except TaskCancelledError" not in client_source
    assert "def collect_history_by_ticker(" in helper_source
    assert "def collect_latest_rows(" in helper_source
    assert "except TaskCancelledError" in helper_source


def test_finmind_rows_retries_retryable_status_before_success(monkeypatch) -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(
        finmind_token=None,
        finmind_max_retries=2,
        finmind_base_retry_delay_seconds=0,
        finmind_max_retry_delay_seconds=0,
    )
    calls = []

    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.headers = {}
            self.request = httpx.Request("GET", "https://api.finmindtrade.com/api/v4/data")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("retryable", request=self.request, response=self)

        def json(self):
            return {"data": [{"date": "2026-05-29", "stock_id": "2330", "close": 1000}]}

    async def fake_get(self, url, params=None, headers=None):
        calls.append(params["dataset"])
        return FakeResponse(429 if len(calls) == 1 else 200)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    rows = asyncio.run(
        client._fetch_finmind_rows("TaiwanStockPrice", "2330", date(2026, 5, 1), date(2026, 5, 31))
    )

    assert len(calls) == 2
    assert rows[0]["stock_id"] == "2330"


def test_finmind_circuit_breaker_opens_after_retryable_failure(monkeypatch) -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(
        finmind_token=None,
        finmind_max_retries=0,
        finmind_base_retry_delay_seconds=0,
        finmind_max_retry_delay_seconds=0,
        finmind_circuit_breaker_enabled=True,
        finmind_circuit_breaker_failure_threshold=1,
        finmind_circuit_breaker_recovery_seconds=60,
    )
    calls = []

    async def fail_get(self, url, params=None, headers=None):
        calls.append(url)
        raise httpx.TransportError("finmind down")

    monkeypatch.setattr("httpx.AsyncClient.get", fail_get)

    with pytest.raises(httpx.TransportError):
        asyncio.run(
            client._fetch_finmind_rows("TaiwanStockPrice", "2330", date(2026, 5, 1), date(2026, 5, 31))
        )
    with pytest.raises(MarketDataProviderUnavailable, match="FinMind circuit breaker is open"):
        asyncio.run(
            client._fetch_finmind_rows("TaiwanStockPrice", "2330", date(2026, 5, 1), date(2026, 5, 31))
        )

    assert calls == ["https://api.finmindtrade.com/api/v4/data"]


def test_fugle_circuit_breaker_opens_after_retryable_failure(monkeypatch) -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(
        fugle_api_key="fugle-key",
        fugle_max_retries=0,
        fugle_base_retry_delay_seconds=0,
        fugle_max_retry_delay_seconds=0,
        fugle_circuit_breaker_enabled=True,
        fugle_circuit_breaker_failure_threshold=1,
        fugle_circuit_breaker_recovery_seconds=60,
    )
    calls = []

    async def fail_get(self, url, params=None, headers=None):
        calls.append(url)
        raise httpx.TransportError("fugle down")

    monkeypatch.setattr("httpx.AsyncClient.get", fail_get)

    with pytest.raises(httpx.TransportError):
        asyncio.run(client._fetch_fugle_json("https://api.fugle.tw/test", params={}))
    with pytest.raises(MarketDataProviderUnavailable, match="Fugle circuit breaker is open"):
        asyncio.run(client._fetch_fugle_json("https://api.fugle.tw/test", params={}))

    assert calls == ["https://api.fugle.tw/test"]


def test_fugle_provider_logic_lives_outside_client() -> None:
    client_source = Path("app/data_sources/market.py").read_text()
    fugle_source = Path("app/data_sources/market_fugle.py").read_text()

    assert (
        market_fugle.FUGLE_HISTORICAL_CANDLES_URL
        == "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{ticker}"
    )
    assert "market_fugle.fetch_fugle_json" in client_source
    assert "market_fugle.fetch_price_history" in client_source
    assert "def fetch_historical_candle_rows(" in fugle_source
    assert "FUGLE_HISTORICAL_CANDLES_URL" in fugle_source
    assert "client.get(" not in client_source.split("async def _fetch_fugle_json(", maxsplit=1)[1].split(
        "async def _fetch_official_openapi_price_snapshot(",
        maxsplit=1,
    )[0]
    assert "candle_error" not in client_source.split(
        "async def _fetch_fugle_price_history(",
        maxsplit=1,
    )[1].split("async def _fetch_fugle_historical_candle_rows(", maxsplit=1)[0]


def test_fugle_retry_delay_uses_retry_after_header() -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(
        fugle_max_retries=2,
        fugle_base_retry_delay_seconds=0.5,
        fugle_max_retry_delay_seconds=5.0,
    )
    response = httpx.Response(
        429,
        headers={"Retry-After": "2.5"},
        request=httpx.Request("GET", "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/2330"),
    )

    helper_delay = market_provider_runtime.retry_delay_seconds(
        response,
        attempt=0,
        base_retry_delay_seconds=0.5,
        max_retry_delay_seconds=5.0,
    )

    assert client._fugle_retry_delay_seconds(response, attempt=0) == 2.5
    assert helper_delay == client._fugle_retry_delay_seconds(response, attempt=0)


def test_fugle_row_to_snapshot() -> None:
    row = {
        "date": "2026-05-29",
        "symbol": "2330",
        "open": "1000",
        "high": "1010",
        "low": "990",
        "close": "1005",
        "volume": "123",
        "turnover": "456",
        "change": "5",
    }
    snapshot = MarketDataClient._fugle_row_to_snapshot(row, "2330")
    helper_snapshot = market_parsers.fugle_row_to_snapshot(row, "2330")

    assert snapshot.ticker == "2330"
    assert snapshot.trade_date == date(2026, 5, 29)
    assert snapshot.high == 1010.0
    assert snapshot.trading_volume == 123
    assert snapshot.trading_money == 456
    assert snapshot.source == "Fugle historical candles"
    assert comparable_market_model(helper_snapshot) == comparable_market_model(snapshot)


def test_fugle_stats_row_to_snapshot() -> None:
    row = {
        "date": "2026-05-29",
        "symbol": "2330",
        "openPrice": "1000",
        "highPrice": "1010",
        "lowPrice": "990",
        "closePrice": "1005",
        "tradeVolume": "123",
        "tradeValue": "456",
        "change": "5",
    }
    snapshot = MarketDataClient._fugle_stats_row_to_snapshot(row, "2330")
    helper_snapshot = market_parsers.fugle_stats_row_to_snapshot(row, "2330")

    assert snapshot.ticker == "2330"
    assert snapshot.trade_date == date(2026, 5, 29)
    assert snapshot.close == 1005.0
    assert snapshot.trading_volume == 123
    assert snapshot.trading_money == 456
    assert snapshot.source == "Fugle historical stats"
    assert comparable_market_model(helper_snapshot) == comparable_market_model(snapshot)


def test_finmind_rows_does_not_retry_non_retryable_status(monkeypatch) -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(
        finmind_token=None,
        finmind_max_retries=3,
        finmind_base_retry_delay_seconds=0,
        finmind_max_retry_delay_seconds=0,
    )
    calls = []

    class FakeResponse:
        status_code = 404
        headers = {}
        request = httpx.Request("GET", "https://api.finmindtrade.com/api/v4/data")

        def raise_for_status(self):
            raise httpx.HTTPStatusError("not found", request=self.request, response=self)

    async def fake_get(self, url, params=None, headers=None):
        calls.append(params["dataset"])
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            client._fetch_finmind_rows("TaiwanStockPrice", "2330", date(2026, 5, 1), date(2026, 5, 31))
        )

    assert calls == ["TaiwanStockPrice"]


def test_finmind_retry_delay_uses_retry_after_header() -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(
        finmind_max_retries=2,
        finmind_base_retry_delay_seconds=0.5,
        finmind_max_retry_delay_seconds=5.0,
    )
    response = httpx.Response(
        429,
        headers={"Retry-After": "3.5"},
        request=httpx.Request("GET", "https://api.finmindtrade.com/api/v4/data"),
    )

    helper_delay = market_provider_runtime.retry_delay_seconds(
        response,
        attempt=0,
        base_retry_delay_seconds=0.5,
        max_retry_delay_seconds=5.0,
    )

    assert client._retry_delay_seconds(response, attempt=0) == 3.5
    assert helper_delay == client._retry_delay_seconds(response, attempt=0)


def test_finmind_row_to_monthly_revenue() -> None:
    row = {
        "date": "2026-04-10",
        "stock_id": "2330",
        "revenue": "349567000000",
        "revenue_year": "2026",
        "revenue_month": "4",
    }
    revenue = MarketDataClient._row_to_monthly_revenue(row)
    helper_revenue = market_parsers.row_to_monthly_revenue(row)

    assert revenue.ticker == "2330"
    assert revenue.revenue_date == date(2026, 4, 10)
    assert revenue.revenue == 349567000000
    assert comparable_market_model(helper_revenue) == comparable_market_model(revenue)
    assert revenue.revenue_month == 4


def test_finmind_row_to_financial_metric() -> None:
    row = {
        "date": "2026-03-31",
        "stock_id": "2330",
        "type": "營業收入",
        "value": "839254000000",
        "origin_name": "營業收入合計",
    }
    metric = MarketDataClient._row_to_financial_metric(
        row,
        "income_statement",
        "TaiwanStockFinancialStatements",
    )
    helper_metric = market_parsers.row_to_financial_metric(
        row,
        "income_statement",
        "TaiwanStockFinancialStatements",
    )

    assert metric.ticker == "2330"
    assert metric.report_date == date(2026, 3, 31)
    assert metric.statement_type == "income_statement"
    assert metric.metric == "營業收入"
    assert comparable_market_model(helper_metric) == comparable_market_model(metric)
    assert metric.value == 839254000000.0


def test_stale_cache_source_marker_is_preserved_when_source_is_long() -> None:
    long_source = "FinMind " + "TaiwanStockPER-" * 12
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 20),
        pe_ratio=24.5,
        pb_ratio=5.8,
        source=long_source,
    )

    marked = MarketDataClient._mark_stale_cache_source(valuation)

    assert MarketDataClient.STALE_CACHE_SOURCE_MARKER in marked.source
    assert len(marked.source) <= 100


def test_finmind_row_to_valuation_metric() -> None:
    row = {
        "date": "2026-05-22",
        "stock_id": "2330",
        "PER": "24.5",
        "PBR": "5.8",
        "dividend_yield": "1.6",
    }
    valuation = MarketDataClient._row_to_valuation_metric(row)
    helper_valuation = market_parsers.row_to_valuation_metric(row)

    assert valuation.ticker == "2330"
    assert valuation.trade_date == date(2026, 5, 22)
    assert valuation.pe_ratio == 24.5
    assert comparable_market_model(helper_valuation) == comparable_market_model(valuation)
    assert valuation.pb_ratio == 5.8
    assert valuation.dividend_yield == 1.6
