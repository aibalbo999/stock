from __future__ import annotations

import fnmatch
from datetime import date

from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric
from app.services.market_data_cache import RedisMarketDataCache


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}
        self.ttls = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttls[key] = ttl

    def scan_iter(self, match: str):
        for key in self.values:
            if fnmatch.fnmatch(key, match):
                yield key


def test_redis_market_data_cache_roundtrips_financial_metrics() -> None:
    fake_redis = FakeRedis()
    cache = RedisMarketDataCache(
        redis_url="redis://cache.example/0",
        enabled=True,
        financial_metrics_ttl_seconds=123,
        client_factory=lambda _url: fake_redis,
    )
    metric = FinancialMetric(
        ticker="2330",
        report_date=date(2026, 3, 31),
        statement_type="income_statement",
        metric="營業收入",
        value=100.0,
        origin_name="營業收入合計",
        source="FinMind TaiwanStockFinancialStatements",
    )

    cache.set_financial_metrics("2330", date(2022, 1, 1), date(2026, 5, 31), [metric])
    cached = cache.get_financial_metrics("2330", date(2022, 1, 1), date(2026, 5, 31))

    assert cached == [metric]
    assert next(iter(fake_redis.ttls.values())) == 123


def test_redis_market_data_cache_latest_financial_metrics_uses_newest_cached_range() -> None:
    fake_redis = FakeRedis()
    cache = RedisMarketDataCache(
        redis_url="redis://cache.example/0",
        enabled=True,
        client_factory=lambda _url: fake_redis,
    )
    old_metric = FinancialMetric(
        ticker="2330",
        report_date=date(2025, 12, 31),
        statement_type="income_statement",
        metric="營業收入",
        value=80.0,
        source="FinMind TaiwanStockFinancialStatements",
    )
    new_metric = FinancialMetric(
        ticker="2330",
        report_date=date(2026, 3, 31),
        statement_type="income_statement",
        metric="營業收入",
        value=100.0,
        source="FinMind TaiwanStockFinancialStatements",
    )

    cache.set_financial_metrics("2330", date(2021, 1, 1), date(2025, 12, 31), [old_metric])
    cache.set_financial_metrics("2330", date(2022, 1, 1), date(2026, 5, 31), [new_metric])

    cached = cache.get_latest_financial_metrics("2330")

    assert cached == [new_metric]


def test_redis_market_data_cache_roundtrips_price_history() -> None:
    fake_redis = FakeRedis()
    cache = RedisMarketDataCache(
        redis_url="redis://cache.example/0",
        enabled=True,
        price_history_ttl_seconds=321,
        client_factory=lambda _url: fake_redis,
    )
    snapshot = MarketSnapshot(
        ticker="2330",
        trade_date=date(2026, 5, 29),
        open=1000,
        high=1010,
        low=990,
        close=1005,
    )

    cache.set_price_history("2330", date(2026, 5, 1), date(2026, 5, 31), [snapshot])
    cached = cache.get_price_history("2330", date(2026, 5, 1), date(2026, 5, 31))

    assert cached == [snapshot]
    assert next(iter(fake_redis.ttls.values())) == 321


def test_redis_market_data_cache_roundtrips_monthly_revenue() -> None:
    fake_redis = FakeRedis()
    cache = RedisMarketDataCache(
        redis_url="redis://cache.example/0",
        enabled=True,
        monthly_revenue_ttl_seconds=654,
        client_factory=lambda _url: fake_redis,
    )
    revenue = MonthlyRevenue(
        ticker="2330",
        revenue_date=date(2026, 4, 10),
        revenue=349_567,
        revenue_year=2026,
        revenue_month=4,
    )

    cache.set_monthly_revenue_history("2330", date(2025, 5, 1), date(2026, 5, 31), [revenue])
    cached = cache.get_monthly_revenue_history("2330", date(2025, 5, 1), date(2026, 5, 31))

    assert cached == [revenue]
    assert next(iter(fake_redis.ttls.values())) == 654


def test_redis_market_data_cache_roundtrips_valuation_history() -> None:
    fake_redis = FakeRedis()
    cache = RedisMarketDataCache(
        redis_url="redis://cache.example/0",
        enabled=True,
        valuation_metrics_ttl_seconds=456,
        client_factory=lambda _url: fake_redis,
    )
    valuation = ValuationMetric(
        ticker="2330",
        trade_date=date(2026, 5, 29),
        pe_ratio=24.5,
        pb_ratio=5.8,
        dividend_yield=1.6,
    )

    cache.set_valuation_history("2330", date(2026, 5, 1), date(2026, 5, 31), [valuation])
    cached = cache.get_valuation_history("2330", date(2026, 5, 1), date(2026, 5, 31))

    assert cached == [valuation]
    assert next(iter(fake_redis.ttls.values())) == 456


def test_redis_market_data_cache_disables_after_redis_error() -> None:
    def broken_factory(_url: str):
        raise RuntimeError("redis down")

    cache = RedisMarketDataCache(
        redis_url="redis://cache.example/0",
        enabled=True,
        client_factory=broken_factory,
    )

    assert cache.get_financial_metrics("2330", date(2022, 1, 1), date(2026, 5, 31)) is None
    assert cache.available is False
