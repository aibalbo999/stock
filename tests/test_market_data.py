import asyncio
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.market import MarketDataClient, MarketDataProviderUnavailable
from app.db.models import Base
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.persistence import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    RiskClassificationRepository,
    ValuationMetricRepository,
)
from app.services.task_cancellation import TaskCancelledError


class FakeMarketDataCache:
    def __init__(
        self,
        cached_price_history=None,
        cached_monthly_revenue_history=None,
        cached_financial_metrics=None,
        cached_valuation_history=None,
        stale_price_history=None,
        stale_monthly_revenue_history=None,
        stale_financial_metrics=None,
        stale_valuation_history=None,
    ) -> None:
        self.cached_price_history = cached_price_history
        self.cached_monthly_revenue_history = cached_monthly_revenue_history
        self.cached_financial_metrics = cached_financial_metrics
        self.cached_valuation_history = cached_valuation_history
        self.stale_price_history = stale_price_history
        self.stale_monthly_revenue_history = stale_monthly_revenue_history
        self.stale_financial_metrics = stale_financial_metrics
        self.stale_valuation_history = stale_valuation_history
        self.stored_price_history = None
        self.stored_monthly_revenue_history = None
        self.stored_financial_metrics = None
        self.stored_valuation_history = None

    def get_price_history(self, ticker: str, start_date: date, end_date: date):
        return self.cached_price_history

    def get_latest_price_history(self, ticker: str):
        return self.stale_price_history

    def set_price_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        snapshots: list[MarketSnapshot],
    ) -> None:
        self.stored_price_history = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "snapshots": snapshots,
        }

    def get_monthly_revenue_history(self, ticker: str, start_date: date, end_date: date):
        return self.cached_monthly_revenue_history

    def get_latest_monthly_revenue_history(self, ticker: str):
        return self.stale_monthly_revenue_history

    def set_monthly_revenue_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        revenues: list[MonthlyRevenue],
    ) -> None:
        self.stored_monthly_revenue_history = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "revenues": revenues,
        }

    def get_financial_metrics(self, ticker: str, start_date: date, end_date: date):
        return self.cached_financial_metrics

    def get_latest_financial_metrics(self, ticker: str):
        return self.stale_financial_metrics

    def set_financial_metrics(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        metrics: list[FinancialMetric],
    ) -> None:
        self.stored_financial_metrics = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "metrics": metrics,
        }

    def get_valuation_history(self, ticker: str, start_date: date, end_date: date):
        return self.cached_valuation_history

    def get_latest_valuation_history(self, ticker: str):
        return self.stale_valuation_history

    def set_valuation_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        valuations: list[ValuationMetric],
    ) -> None:
        self.stored_valuation_history = {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "valuations": valuations,
        }


def test_finmind_row_to_snapshot() -> None:
    snapshot = MarketDataClient._row_to_snapshot(
        {
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
    )

    assert snapshot.ticker == "2330"
    assert snapshot.trade_date == date(2026, 5, 22)
    assert snapshot.high == 1010.0
    assert snapshot.trading_volume == 123


def test_finmind_public_fallback_can_be_disabled_without_token() -> None:
    client = MarketDataClient()
    client.settings = SimpleNamespace(finmind_token=None, finmind_public_fallback_enabled=False)

    with pytest.raises(MarketDataProviderUnavailable, match="public fallback is disabled"):
        asyncio.run(client._fetch_finmind_rows("TaiwanStockPrice", "2330", date(2026, 5, 1), date(2026, 5, 31)))


def test_price_history_uses_redis_cache_hit(monkeypatch) -> None:
    client = MarketDataClient()
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1005)
    client.cache = FakeMarketDataCache(cached_price_history=[snapshot])

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("FinMind should not be called on cache hit")

    monkeypatch.setattr("httpx.AsyncClient.get", fail_fetch)

    snapshots = asyncio.run(client.get_price_history("2330", date(2026, 5, 1), date(2026, 5, 31)))

    assert snapshots == [snapshot]


def test_price_history_force_refresh_bypasses_redis_cache(monkeypatch) -> None:
    client = MarketDataClient()
    cached = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1005)
    refreshed = MarketSnapshot(ticker="2330", trade_date=date(2026, 6, 1), close=1015)
    client.cache = FakeMarketDataCache(cached_price_history=[cached])

    async def fake_fetch(ticker: str, start_date: date, end_date: date):
        assert ticker == "2330"
        return [refreshed]

    monkeypatch.setattr(client, "_fetch_price_history_uncached", fake_fetch)

    snapshots = asyncio.run(
        client.get_price_history(
            "2330",
            date(2026, 5, 1),
            date(2026, 6, 1),
            force_refresh=True,
        )
    )

    assert snapshots == [refreshed]
    assert client.cache.stored_price_history["snapshots"] == [refreshed]


def test_price_history_stores_cache_after_fetch(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "date": "2026-05-29",
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
                ]
            }

    async def fake_get(self, url, params=None, headers=None):
        assert params["dataset"] == "TaiwanStockPrice"
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    snapshots = asyncio.run(client.get_price_history("2330", date(2026, 5, 1), date(2026, 5, 31)))

    assert len(snapshots) == 1
    assert cache.stored_price_history["ticker"] == "2330"
    assert cache.stored_price_history["snapshots"] == snapshots


def test_price_history_falls_back_to_fugle_when_finmind_fails(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache
    client.settings = SimpleNamespace(
        finmind_token=None,
        finmind_max_retries=0,
        finmind_base_retry_delay_seconds=0,
        finmind_max_retry_delay_seconds=0,
        fugle_api_key="fugle-key",
        fugle_max_retries=0,
        fugle_base_retry_delay_seconds=0,
        fugle_max_retry_delay_seconds=0,
        market_price_provider_order="finmind,fugle",
    )
    calls = []

    class FakeFinMindResponse:
        status_code = 503
        headers = {}
        request = httpx.Request("GET", "https://api.finmindtrade.com/api/v4/data")

        def raise_for_status(self):
            raise httpx.HTTPStatusError("finmind down", request=self.request, response=self)

    class FakeFugleResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "date": "2026-05-29",
                        "open": 1000.0,
                        "high": 1010.0,
                        "low": 990.0,
                        "close": 1005.0,
                        "volume": 123,
                        "turnover": 456,
                        "change": 5.0,
                    }
                ]
            }

    async def fake_get(self, url, params=None, headers=None):
        calls.append(url)
        if "finmindtrade" in url:
            return FakeFinMindResponse()
        assert url.endswith("/historical/candles/2330")
        assert params["from"] == "2026-05-01"
        assert params["to"] == "2026-05-31"
        assert params["timeframe"] == "D"
        assert params["sort"] == "asc"
        assert headers["X-API-KEY"] == "fugle-key"
        return FakeFugleResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    snapshots = asyncio.run(client.get_price_history("2330", date(2026, 5, 1), date(2026, 5, 31)))

    assert calls == [
        "https://api.finmindtrade.com/api/v4/data",
        "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/2330",
    ]
    assert snapshots[0].source == "Fugle historical candles"
    assert snapshots[0].trading_volume == 123
    assert cache.stored_price_history["snapshots"] == snapshots


def test_price_history_uses_fugle_stats_when_fugle_candles_are_empty(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache
    client.settings = SimpleNamespace(
        fugle_api_key="fugle-key",
        fugle_max_retries=0,
        fugle_base_retry_delay_seconds=0,
        fugle_max_retry_delay_seconds=0,
        market_price_provider_order="fugle",
    )
    calls = []

    class FakeFugleResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    async def fake_get(self, url, params=None, headers=None):
        calls.append(url)
        assert headers["X-API-KEY"] == "fugle-key"
        if url.endswith("/historical/candles/2330"):
            return FakeFugleResponse({"data": []})
        assert url.endswith("/historical/stats/2330")
        return FakeFugleResponse(
            {
                "date": "2026-05-29",
                "symbol": "2330",
                "openPrice": 1000.0,
                "highPrice": 1010.0,
                "lowPrice": 990.0,
                "closePrice": 1005.0,
                "change": 5.0,
                "tradeVolume": 123,
                "tradeValue": 456,
            }
        )

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    snapshots = asyncio.run(client.get_price_history("2330", date(2026, 5, 1), date(2026, 5, 31)))

    assert calls == [
        "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/2330",
        "https://api.fugle.tw/marketdata/v1.0/stock/historical/stats/2330",
    ]
    assert snapshots[0].source == "Fugle historical stats"
    assert snapshots[0].close == 1005.0
    assert cache.stored_price_history["snapshots"] == snapshots


def test_price_history_uses_stale_cache_when_finmind_fails(monkeypatch) -> None:
    client = MarketDataClient()
    snapshot = MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 20), close=1000)
    client.cache = FakeMarketDataCache(stale_price_history=[snapshot])

    async def fail_fetch(*_args, **_kwargs):
        raise TimeoutError("finmind timeout")

    monkeypatch.setattr("httpx.AsyncClient.get", fail_fetch)

    snapshots = asyncio.run(client.get_price_history("2330", date(2026, 5, 1), date(2026, 5, 31)))

    assert snapshots[0].source == "FinMind TaiwanStockPrice; cached-stale"


def test_price_history_uses_official_openapi_snapshot_fallback(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache
    client.settings = SimpleNamespace(
        finmind_token=None,
        finmind_max_retries=0,
        finmind_base_retry_delay_seconds=0,
        finmind_max_retry_delay_seconds=0,
        fugle_api_key="",
        market_price_provider_order="finmind,fugle",
        market_official_openapi_fallback_enabled=True,
    )

    async def fail_finmind(*_args, **_kwargs):
        raise TimeoutError("finmind timeout")

    async def fake_official_rows(url: str):
        if url.endswith("/exchangeReport/STOCK_DAY_ALL"):
            return [
                {
                    "Date": "1150529",
                    "Code": "2330",
                    "OpeningPrice": "1000",
                    "HighestPrice": "1010",
                    "LowestPrice": "990",
                    "ClosingPrice": "1005",
                    "Change": "+5.0",
                    "TradeVolume": "123",
                    "TradeValue": "456",
                }
            ]
        return []

    monkeypatch.setattr(client, "_fetch_finmind_rows", fail_finmind)
    monkeypatch.setattr(client, "_fetch_official_openapi_rows", fake_official_rows)

    snapshots = asyncio.run(client.get_price_history("2330", date(2026, 5, 1), date(2026, 5, 31)))

    assert snapshots[0].trade_date == date(2026, 5, 29)
    assert snapshots[0].source == "TWSE OpenAPI STOCK_DAY_ALL; latest-only"
    assert cache.stored_price_history["snapshots"] == snapshots


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

    assert client._fugle_retry_delay_seconds(response, attempt=0) == 2.5


def test_fugle_row_to_snapshot() -> None:
    snapshot = MarketDataClient._fugle_row_to_snapshot(
        {
            "date": "2026-05-29",
            "symbol": "2330",
            "open": "1000",
            "high": "1010",
            "low": "990",
            "close": "1005",
            "volume": "123",
            "turnover": "456",
            "change": "5",
        },
        "2330",
    )

    assert snapshot.ticker == "2330"
    assert snapshot.trade_date == date(2026, 5, 29)
    assert snapshot.high == 1010.0
    assert snapshot.trading_volume == 123
    assert snapshot.trading_money == 456
    assert snapshot.source == "Fugle historical candles"


def test_fugle_stats_row_to_snapshot() -> None:
    snapshot = MarketDataClient._fugle_stats_row_to_snapshot(
        {
            "date": "2026-05-29",
            "symbol": "2330",
            "openPrice": "1000",
            "highPrice": "1010",
            "lowPrice": "990",
            "closePrice": "1005",
            "tradeVolume": "123",
            "tradeValue": "456",
            "change": "5",
        },
        "2330",
    )

    assert snapshot.ticker == "2330"
    assert snapshot.trade_date == date(2026, 5, 29)
    assert snapshot.close == 1005.0
    assert snapshot.trading_volume == 123
    assert snapshot.trading_money == 456
    assert snapshot.source == "Fugle historical stats"


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

    assert client._retry_delay_seconds(response, attempt=0) == 3.5


def test_finmind_row_to_monthly_revenue() -> None:
    revenue = MarketDataClient._row_to_monthly_revenue(
        {
            "date": "2026-04-10",
            "stock_id": "2330",
            "revenue": "349567000000",
            "revenue_year": "2026",
            "revenue_month": "4",
        }
    )

    assert revenue.ticker == "2330"
    assert revenue.revenue_date == date(2026, 4, 10)
    assert revenue.revenue == 349567000000
    assert revenue.revenue_month == 4


def test_monthly_revenue_history_uses_redis_cache_hit(monkeypatch) -> None:
    client = MarketDataClient()
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349_567,
        revenue_year=2026,
        revenue_month=4,
    )
    client.cache = FakeMarketDataCache(cached_monthly_revenue_history=[revenue])

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("FinMind should not be called on cache hit")

    monkeypatch.setattr("httpx.AsyncClient.get", fail_fetch)

    revenues = asyncio.run(client.get_monthly_revenue_history("2330", date(2025, 5, 1), date(2026, 5, 31)))

    assert revenues == [revenue]


def test_monthly_revenue_history_uses_stale_cache_when_finmind_returns_empty(monkeypatch) -> None:
    client = MarketDataClient()
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349_567,
        revenue_year=2026,
        revenue_month=4,
    )
    client.cache = FakeMarketDataCache(stale_monthly_revenue_history=[revenue])

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    async def fake_get(self, url, params=None, headers=None):
        assert params["dataset"] == "TaiwanStockMonthRevenue"
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    revenues = asyncio.run(client.get_monthly_revenue_history("2330", date(2025, 5, 1), date(2026, 5, 31)))

    assert revenues[0].source == "FinMind TaiwanStockMonthRevenue; cached-stale"


def test_monthly_revenue_history_stores_cache_after_fetch(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "date": "2026-04-10",
                        "stock_id": "2330",
                        "revenue": "349567",
                        "revenue_year": "2026",
                        "revenue_month": "4",
                    }
                ]
            }

    async def fake_get(self, url, params=None, headers=None):
        assert params["dataset"] == "TaiwanStockMonthRevenue"
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    revenues = asyncio.run(client.get_monthly_revenue_history("2330", date(2025, 5, 1), date(2026, 5, 31)))

    assert len(revenues) == 1
    assert cache.stored_monthly_revenue_history["ticker"] == "2330"
    assert cache.stored_monthly_revenue_history["revenues"] == revenues


def test_monthly_revenue_history_uses_official_openapi_fallback(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache

    async def empty_finmind(*_args, **_kwargs):
        return []

    async def fake_official_rows(url: str):
        if url.endswith("/opendata/t187ap05_L"):
            return [
                {
                    "資料年月": "11504",
                    "公司代號": "2330",
                    "營業收入-當月營收": "349567000",
                    "營業收入-去年同月增減(%)": "43.92",
                }
            ]
        return []

    monkeypatch.setattr(client, "_fetch_finmind_rows", empty_finmind)
    monkeypatch.setattr(client, "_fetch_official_openapi_rows", fake_official_rows)

    revenues = asyncio.run(client.get_monthly_revenue_history("2330", date(2025, 5, 1), date(2026, 5, 31)))

    assert revenues[0].revenue_date == date(2026, 4, 30)
    assert revenues[0].yoy_pct == 43.92
    assert revenues[0].source == "TWSE OpenAPI t187ap05_L; latest-only"
    assert cache.stored_monthly_revenue_history["revenues"] == revenues


def test_finmind_row_to_financial_metric() -> None:
    metric = MarketDataClient._row_to_financial_metric(
        {
            "date": "2026-03-31",
            "stock_id": "2330",
            "type": "營業收入",
            "value": "839254000000",
            "origin_name": "營業收入合計",
        },
        "income_statement",
        "TaiwanStockFinancialStatements",
    )

    assert metric.ticker == "2330"
    assert metric.report_date == date(2026, 3, 31)
    assert metric.statement_type == "income_statement"
    assert metric.metric == "營業收入"
    assert metric.value == 839254000000.0


def test_financial_metrics_history_uses_redis_cache_hit(monkeypatch) -> None:
    client = MarketDataClient()
    metric = FinancialMetric(
        ticker="2330",
        report_date=date(2026, 3, 31),
        statement_type="income_statement",
        metric="營業收入",
        value=100.0,
        source="FinMind TaiwanStockFinancialStatements",
    )
    client.cache = FakeMarketDataCache(cached_financial_metrics=[metric])

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("FinMind should not be called on cache hit")

    monkeypatch.setattr(client, "_fetch_finmind_rows", fail_fetch)

    metrics = asyncio.run(
        client.get_financial_metrics_history("2330", date(2022, 1, 1), date(2026, 5, 31))
    )

    assert metrics == [metric]


def test_financial_metrics_history_uses_stale_cache_when_finmind_fails(monkeypatch) -> None:
    client = MarketDataClient()
    metric = FinancialMetric(
        ticker="2330",
        report_date=date(2026, 3, 31),
        statement_type="income_statement",
        metric="營業收入",
        value=100.0,
        source="FinMind TaiwanStockFinancialStatements",
    )
    cache = FakeMarketDataCache(stale_financial_metrics=[metric])
    client.cache = cache

    async def fail_fetch(*_args, **_kwargs):
        raise TimeoutError("finmind timeout")

    async def empty_official(*_args, **_kwargs):
        return []

    monkeypatch.setattr(client, "_fetch_finmind_rows", fail_fetch)
    monkeypatch.setattr(client, "_fetch_official_openapi_financial_metrics", empty_official)

    metrics = asyncio.run(
        client.get_financial_metrics_history("2330", date(2022, 1, 1), date(2026, 5, 31))
    )

    assert metrics[0].source == "FinMind TaiwanStockFinancialStatements; cached-stale"
    assert cache.stored_financial_metrics is None


def test_financial_metrics_history_stores_cache_after_fetch(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache
    fetched_datasets = []

    async def fake_fetch(dataset: str, ticker: str, start_date: date, end_date: date):
        fetched_datasets.append(dataset)
        return [
            {
                "date": "2026-03-31",
                "stock_id": ticker,
                "type": f"{dataset}-metric",
                "value": "100",
                "origin_name": f"{dataset}-origin",
            }
        ]

    monkeypatch.setattr(client, "_fetch_finmind_rows", fake_fetch)

    metrics = asyncio.run(
        client.get_financial_metrics_history("2330", date(2022, 1, 1), date(2026, 5, 31))
    )

    assert fetched_datasets == [
        "TaiwanStockFinancialStatements",
        "TaiwanStockBalanceSheet",
        "TaiwanStockCashFlowsStatement",
    ]
    assert len(metrics) == 3
    assert cache.stored_financial_metrics["ticker"] == "2330"
    assert cache.stored_financial_metrics["metrics"] == metrics


def test_financial_metrics_history_uses_official_openapi_fallback(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache

    async def fail_finmind(*_args, **_kwargs):
        raise TimeoutError("finmind timeout")

    async def fake_official_rows(url: str):
        if url.endswith("t187ap06_L_ci"):
            return [
                {
                    "年度": "115",
                    "季別": "1",
                    "公司代號": "2330",
                    "營業收入": "839254000",
                    "本期淨利（淨損）": "361563000",
                }
            ]
        if url.endswith("t187ap07_L_ci"):
            return [
                {
                    "年度": "115",
                    "季別": "1",
                    "公司代號": "2330",
                    "負債總額": "1000",
                    "權益總額": "2500",
                }
            ]
        return []

    monkeypatch.setattr(client, "_fetch_finmind_rows", fail_finmind)
    monkeypatch.setattr(client, "_fetch_official_openapi_rows", fake_official_rows)

    metrics = asyncio.run(
        client.get_financial_metrics_history("2330", date(2022, 1, 1), date(2026, 5, 31))
    )

    names = {metric.metric for metric in metrics}
    assert {"營業收入", "本期淨利（淨損）", "負債總額", "權益總額"} <= names
    assert {metric.report_date for metric in metrics} == {date(2026, 3, 31)}
    assert all(metric.source.startswith("TWSE OpenAPI") for metric in metrics)
    assert all("latest-only" in metric.source for metric in metrics)
    assert cache.stored_financial_metrics["metrics"] == metrics


def test_valuation_history_uses_redis_cache_hit(monkeypatch) -> None:
    client = MarketDataClient()
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 29),
        pe_ratio=24.5,
        pb_ratio=5.8,
        dividend_yield=1.6,
    )
    client.cache = FakeMarketDataCache(cached_valuation_history=[valuation])

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("FinMind should not be called on cache hit")

    monkeypatch.setattr(client, "_fetch_finmind_rows", fail_fetch)

    valuations = asyncio.run(
        client.get_valuation_history("2330", date(2026, 5, 1), date(2026, 5, 31))
    )

    assert valuations == [valuation]


def test_valuation_history_stores_cache_after_fetch(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache

    async def fake_fetch(dataset: str, ticker: str, start_date: date, end_date: date):
        assert dataset == "TaiwanStockPER"
        return [
            {
                "date": "2026-05-29",
                "stock_id": ticker,
                "PER": "24.5",
                "PBR": "5.8",
                "dividend_yield": "1.6",
            }
        ]

    monkeypatch.setattr(client, "_fetch_finmind_rows", fake_fetch)

    valuations = asyncio.run(
        client.get_valuation_history("2330", date(2026, 5, 1), date(2026, 5, 31))
    )

    assert len(valuations) == 1
    assert cache.stored_valuation_history["ticker"] == "2330"
    assert cache.stored_valuation_history["valuations"] == valuations


def test_valuation_history_uses_stale_cache_when_finmind_fails(monkeypatch) -> None:
    client = MarketDataClient()
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 20),
        pe_ratio=24.5,
        pb_ratio=5.8,
        dividend_yield=1.6,
        source="FinMind TaiwanStockPER",
    )
    cache = FakeMarketDataCache(stale_valuation_history=[valuation])
    client.cache = cache

    async def fail_fetch(*_args, **_kwargs):
        raise TimeoutError("FinMind unavailable")

    async def empty_official(*_args, **_kwargs):
        return []

    monkeypatch.setattr(client, "_fetch_finmind_rows", fail_fetch)
    monkeypatch.setattr(client, "_fetch_official_openapi_valuation", empty_official)

    valuations = asyncio.run(
        client.get_valuation_history("2330", date(2026, 5, 1), date(2026, 5, 31))
    )

    assert valuations[0].source == "FinMind TaiwanStockPER; cached-stale"
    assert cache.stored_valuation_history is None


def test_valuation_history_uses_stale_cache_when_finmind_returns_empty(monkeypatch) -> None:
    client = MarketDataClient()
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 20),
        pe_ratio=24.5,
        pb_ratio=5.8,
        dividend_yield=1.6,
        source="FinMind TaiwanStockPER",
    )
    cache = FakeMarketDataCache(stale_valuation_history=[valuation])
    client.cache = cache

    async def empty_fetch(*_args, **_kwargs):
        return []

    async def empty_official(*_args, **_kwargs):
        return []

    monkeypatch.setattr(client, "_fetch_finmind_rows", empty_fetch)
    monkeypatch.setattr(client, "_fetch_official_openapi_valuation", empty_official)

    valuations = asyncio.run(
        client.get_valuation_history("2330", date(2026, 5, 1), date(2026, 5, 31))
    )

    assert valuations[0].source == "FinMind TaiwanStockPER; cached-stale"
    assert cache.stored_valuation_history is None


def test_valuation_history_uses_official_openapi_fallback(monkeypatch) -> None:
    client = MarketDataClient()
    cache = FakeMarketDataCache()
    client.cache = cache

    async def empty_finmind(*_args, **_kwargs):
        return []

    async def fake_official_rows(url: str):
        if url.endswith("/exchangeReport/BWIBBU_ALL"):
            return [
                {
                    "Date": "1150529",
                    "Code": "2330",
                    "PEratio": "24.5",
                    "PBratio": "5.8",
                    "DividendYield": "1.6",
                }
            ]
        return []

    monkeypatch.setattr(client, "_fetch_finmind_rows", empty_finmind)
    monkeypatch.setattr(client, "_fetch_official_openapi_rows", fake_official_rows)

    valuations = asyncio.run(
        client.get_valuation_history("2330", date(2026, 5, 1), date(2026, 5, 31))
    )

    assert valuations[0].trade_date == date(2026, 5, 29)
    assert valuations[0].pe_ratio == 24.5
    assert valuations[0].source == "TWSE OpenAPI BWIBBU_ALL; latest-only"
    assert cache.stored_valuation_history["valuations"] == valuations


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
    valuation = MarketDataClient._row_to_valuation_metric(
        {
            "date": "2026-05-22",
            "stock_id": "2330",
            "PER": "24.5",
            "PBR": "5.8",
            "dividend_yield": "1.6",
        }
    )

    assert valuation.ticker == "2330"
    assert valuation.trade_date == date(2026, 5, 22)
    assert valuation.pe_ratio == 24.5
    assert valuation.pb_ratio == 5.8
    assert valuation.dividend_yield == 1.6


def test_latest_snapshots_collect_partial_errors(monkeypatch) -> None:
    client = MarketDataClient()

    async def fake_get_price_history(ticker: str, start_date: date, end_date: date, *, force_refresh=False):
        if ticker == "2382":
            raise TimeoutError("timeout")
        return [
            MarketSnapshot(ticker=ticker, trade_date=date(2026, 5, 20), close=100.0),
            MarketSnapshot(ticker=ticker, trade_date=date(2026, 5, 22), close=110.0),
        ]

    monkeypatch.setattr(client, "get_price_history", fake_get_price_history)

    snapshots, errors = asyncio.run(
        client.get_latest_snapshots_with_errors(
            ["2330", "2382"],
            date(2026, 5, 1),
            date(2026, 5, 22),
        )
    )

    assert [snapshot.ticker for snapshot in snapshots] == ["2330"]
    assert snapshots[0].trade_date == date(2026, 5, 22)
    assert len(errors) == 1
    assert errors[0].model_dump() == {
        "ticker": "2382",
        "dataset": "TaiwanStockPrice",
        "error": "timeout",
    }


def test_price_histories_keep_all_rows_for_leading_signals(monkeypatch) -> None:
    client = MarketDataClient()

    async def fake_get_price_history(ticker: str, start_date: date, end_date: date, *, force_refresh=False):
        return [
            MarketSnapshot(ticker=ticker, trade_date=date(2026, 5, 20), close=100.0),
            MarketSnapshot(ticker=ticker, trade_date=date(2026, 5, 22), close=110.0),
        ]

    monkeypatch.setattr(client, "get_price_history", fake_get_price_history)

    histories, errors = asyncio.run(
        client.get_price_histories_with_errors(
            ["2330"],
            date(2026, 5, 1),
            date(2026, 5, 22),
        )
    )

    assert errors == []
    assert [snapshot.trade_date for snapshot in histories["2330"]] == [
        date(2026, 5, 20),
        date(2026, 5, 22),
    ]


def test_price_histories_re_raise_task_cancellation() -> None:
    client = MarketDataClient(cancellation_checker=lambda: (_ for _ in ()).throw(TaskCancelledError(7)))

    with pytest.raises(TaskCancelledError):
        asyncio.run(
            client.get_price_histories_with_errors(
                ["2330", "2382"],
                date(2026, 5, 1),
                date(2026, 5, 22),
            )
        )


def test_monthly_revenue_collect_partial_errors(monkeypatch) -> None:
    client = MarketDataClient()

    async def fake_get_monthly_revenue_history(ticker: str, start_date: date, end_date: date):
        if ticker == "2382":
            raise RuntimeError("rate limited")
        return [
            MonthlyRevenue(
                ticker=ticker,
                revenue_date=date(2026, 4, 10),
                revenue=125,
                revenue_year=2026,
                revenue_month=4,
            )
        ]

    monkeypatch.setattr(client, "get_monthly_revenue_history", fake_get_monthly_revenue_history)

    revenues, errors = asyncio.run(
        client.get_monthly_revenue_histories_with_errors(
            ["2330", "2382"],
            date(2025, 1, 1),
            date(2026, 5, 22),
        )
    )

    assert [revenue.ticker for revenue in revenues] == ["2330"]
    assert len(errors) == 1
    assert errors[0].model_dump() == {
        "ticker": "2382",
        "dataset": "TaiwanStockMonthRevenue",
        "error": "rate limited",
    }


def test_market_repository_upsert_and_latest() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = MarketRepository(session)
        repository.upsert_snapshots(
            [
                MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 21), close=1000.0),
                MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 22), close=1010.0),
            ]
        )
        session.commit()

        latest = repository.latest_by_tickers(["2330"])

        assert len(latest) == 1
        assert latest[0].trade_date == date(2026, 5, 22)
        assert latest[0].close == 1010.0
        history = repository.history_by_tickers(["2330"], limit=10)
        assert [snapshot.trade_date for snapshot in history["2330"]] == [
            date(2026, 5, 21),
            date(2026, 5, 22),
        ]
    finally:
        session.close()


def test_monthly_revenue_repository_upsert_and_yoy() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = MonthlyRevenueRepository(session)
        repository.upsert_revenues(
            [
                MonthlyRevenue(
                    ticker="2330",
                    revenue_date=date(2025, 4, 10),
                    revenue=100,
                    revenue_year=2025,
                    revenue_month=4,
                ),
                MonthlyRevenue(
                    ticker="2330",
                    revenue_date=date(2026, 4, 10),
                    revenue=125,
                    revenue_year=2026,
                    revenue_month=4,
                ),
            ]
        )
        session.commit()

        latest = repository.latest_by_tickers(["2330"])

        assert len(latest) == 1
        assert latest[0].revenue_date == date(2026, 4, 10)
        assert latest[0].yoy_pct == 25.0
    finally:
        session.close()


def test_financial_and_valuation_repository_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        FinancialMetricRepository(session).upsert_metrics(
            [
                FinancialMetric(
                    ticker="2330",
                    report_date=date(2026, 3, 31),
                    statement_type="income_statement",
                    metric="營業收入",
                    value=1000.0,
                    origin_name="營業收入合計",
                    source="FinMind TaiwanStockFinancialStatements",
                )
            ]
        )
        ValuationMetricRepository(session).upsert_valuations(
            [
                ValuationMetric(
                    ticker="2330",
                    trade_date=date(2026, 5, 22),
                    pe_ratio=24.5,
                    pb_ratio=5.8,
                    dividend_yield=1.6,
                )
            ]
        )
        session.commit()

        metrics = FinancialMetricRepository(session).by_tickers(["2330"])
        valuations = ValuationMetricRepository(session).latest_by_tickers(["2330"])

        assert metrics[0].metric == "營業收入"
        assert metrics[0].value == 1000.0
        assert valuations[0].pe_ratio == 24.5
    finally:
        session.close()


def test_risk_classification_repository_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = RiskClassificationRepository(session)
        repository.upsert(
            document_id="doc-1",
            topic_hash="topic-a",
            classification="opportunity_or_growth",
            topic="需求成長",
            evidence="需求旺",
            confidence=0.9,
            keywords=["需求旺"],
            model="gemini-test",
        )
        session.commit()

        cached = repository.get("doc-1", "topic-a")

        assert cached["classification"] == "opportunity_or_growth"
        assert cached["topic_hash"] == "topic-a"
        assert cached["keywords"] == ["需求旺"]
        assert cached["model"] == "gemini-test"
    finally:
        session.close()
