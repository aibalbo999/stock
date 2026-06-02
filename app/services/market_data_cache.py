from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

import redis

from app.core.config import get_settings
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric


class RedisMarketDataCache:
    """Best-effort Redis cache for low-frequency market data."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        enabled: bool | None = None,
        price_history_ttl_seconds: int | None = None,
        monthly_revenue_ttl_seconds: int | None = None,
        financial_metrics_ttl_seconds: int | None = None,
        valuation_metrics_ttl_seconds: int | None = None,
        client_factory: Callable[[str], object] | None = None,
    ) -> None:
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.enabled = settings.market_data_cache_enabled if enabled is None else enabled
        self.price_history_ttl_seconds = (
            int(settings.price_history_cache_ttl_seconds)
            if price_history_ttl_seconds is None
            else int(price_history_ttl_seconds)
        )
        self.monthly_revenue_ttl_seconds = (
            int(settings.monthly_revenue_cache_ttl_seconds)
            if monthly_revenue_ttl_seconds is None
            else int(monthly_revenue_ttl_seconds)
        )
        self.financial_metrics_ttl_seconds = (
            int(settings.financial_metrics_cache_ttl_seconds)
            if financial_metrics_ttl_seconds is None
            else int(financial_metrics_ttl_seconds)
        )
        self.valuation_metrics_ttl_seconds = (
            int(settings.valuation_metrics_cache_ttl_seconds)
            if valuation_metrics_ttl_seconds is None
            else int(valuation_metrics_ttl_seconds)
        )
        self._client_factory = client_factory or self._default_client_factory
        self._client: object | None = None
        self._disabled_after_error = False

    def get_price_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketSnapshot] | None:
        payload = self._get_json(self._price_history_key(ticker, start_date, end_date))
        if not isinstance(payload, list):
            return None
        try:
            return [MarketSnapshot.model_validate(item) for item in payload]
        except Exception:
            return None

    def get_latest_price_history(self, ticker: str) -> list[MarketSnapshot] | None:
        payload = self._get_latest_json_for_prefix(self._price_history_prefix(ticker))
        if not isinstance(payload, list):
            return None
        try:
            return [MarketSnapshot.model_validate(item) for item in payload]
        except Exception:
            return None

    def set_price_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        snapshots: list[MarketSnapshot],
    ) -> None:
        if not snapshots:
            return
        self._set_json(
            self._price_history_key(ticker, start_date, end_date),
            [snapshot.model_dump(mode="json") for snapshot in snapshots],
            self.price_history_ttl_seconds,
        )

    def get_monthly_revenue_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[MonthlyRevenue] | None:
        payload = self._get_json(self._monthly_revenue_key(ticker, start_date, end_date))
        if not isinstance(payload, list):
            return None
        try:
            return [MonthlyRevenue.model_validate(item) for item in payload]
        except Exception:
            return None

    def get_latest_monthly_revenue_history(self, ticker: str) -> list[MonthlyRevenue] | None:
        payload = self._get_latest_json_for_prefix(self._monthly_revenue_prefix(ticker))
        if not isinstance(payload, list):
            return None
        try:
            return [MonthlyRevenue.model_validate(item) for item in payload]
        except Exception:
            return None

    def set_monthly_revenue_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        revenues: list[MonthlyRevenue],
    ) -> None:
        if not revenues:
            return
        self._set_json(
            self._monthly_revenue_key(ticker, start_date, end_date),
            [revenue.model_dump(mode="json") for revenue in revenues],
            self.monthly_revenue_ttl_seconds,
        )

    def get_financial_metrics(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[FinancialMetric] | None:
        payload = self._get_json(self._financial_metrics_key(ticker, start_date, end_date))
        if not isinstance(payload, list):
            return None
        try:
            return [FinancialMetric.model_validate(item) for item in payload]
        except Exception:
            return None

    def get_latest_financial_metrics(self, ticker: str) -> list[FinancialMetric] | None:
        payload = self._get_latest_json_for_prefix(self._financial_metrics_prefix(ticker))
        if not isinstance(payload, list):
            return None
        try:
            return [FinancialMetric.model_validate(item) for item in payload]
        except Exception:
            return None

    def set_financial_metrics(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        metrics: list[FinancialMetric],
    ) -> None:
        if not metrics:
            return
        self._set_json(
            self._financial_metrics_key(ticker, start_date, end_date),
            [metric.model_dump(mode="json") for metric in metrics],
            self.financial_metrics_ttl_seconds,
        )

    def get_valuation_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetric] | None:
        payload = self._get_json(self._valuation_history_key(ticker, start_date, end_date))
        if not isinstance(payload, list):
            return None
        try:
            return [ValuationMetric.model_validate(item) for item in payload]
        except Exception:
            return None

    def get_latest_valuation_history(self, ticker: str) -> list[ValuationMetric] | None:
        payload = self._get_latest_json_for_prefix(self._valuation_history_prefix(ticker))
        if not isinstance(payload, list):
            return None
        try:
            return [ValuationMetric.model_validate(item) for item in payload]
        except Exception:
            return None

    def set_valuation_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        valuations: list[ValuationMetric],
    ) -> None:
        if not valuations:
            return
        self._set_json(
            self._valuation_history_key(ticker, start_date, end_date),
            [valuation.model_dump(mode="json") for valuation in valuations],
            self.valuation_metrics_ttl_seconds,
        )

    @property
    def available(self) -> bool:
        return self.enabled and not self._disabled_after_error

    @staticmethod
    def _price_history_key(ticker: str, start_date: date, end_date: date) -> str:
        return f"{RedisMarketDataCache._price_history_prefix(ticker)}{start_date.isoformat()}:{end_date.isoformat()}"

    @staticmethod
    def _monthly_revenue_key(ticker: str, start_date: date, end_date: date) -> str:
        return f"{RedisMarketDataCache._monthly_revenue_prefix(ticker)}{start_date.isoformat()}:{end_date.isoformat()}"

    @staticmethod
    def _financial_metrics_key(ticker: str, start_date: date, end_date: date) -> str:
        return f"{RedisMarketDataCache._financial_metrics_prefix(ticker)}{start_date.isoformat()}:{end_date.isoformat()}"

    @staticmethod
    def _valuation_history_key(ticker: str, start_date: date, end_date: date) -> str:
        return f"{RedisMarketDataCache._valuation_history_prefix(ticker)}{start_date.isoformat()}:{end_date.isoformat()}"

    @staticmethod
    def _price_history_prefix(ticker: str) -> str:
        return f"stock-ai:market:price_history:v1:{ticker}:"

    @staticmethod
    def _monthly_revenue_prefix(ticker: str) -> str:
        return f"stock-ai:market:monthly_revenue:v1:{ticker}:"

    @staticmethod
    def _financial_metrics_prefix(ticker: str) -> str:
        return f"stock-ai:market:financial_metrics:v1:{ticker}:"

    @staticmethod
    def _valuation_history_prefix(ticker: str) -> str:
        return f"stock-ai:market:valuation_history:v1:{ticker}:"

    @staticmethod
    def _default_client_factory(redis_url: str) -> object:
        return redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
        )

    def _redis(self) -> object | None:
        if not self.enabled or self._disabled_after_error:
            return None
        if self._client is not None:
            return self._client
        try:
            self._client = self._client_factory(self.redis_url)
            return self._client
        except Exception:
            self._disabled_after_error = True
            return None

    def _get_json(self, key: str) -> object | None:
        client = self._redis()
        if client is None:
            return None
        try:
            raw = client.get(key)
        except Exception:
            self._disabled_after_error = True
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _get_latest_json_for_prefix(self, prefix: str) -> object | None:
        candidates: list[tuple[date, date, str]] = []
        for key in self._scan_keys(f"{prefix}*"):
            parsed_range = self._parse_key_date_range(key)
            if parsed_range is None:
                continue
            start_date, end_date = parsed_range
            candidates.append((end_date, start_date, key))
        for _end_date, _start_date, key in sorted(candidates, reverse=True):
            payload = self._get_json(key)
            if isinstance(payload, list):
                return payload
        return None

    def _scan_keys(self, pattern: str) -> list[str]:
        client = self._redis()
        if client is None:
            return []
        try:
            scan_iter = getattr(client, "scan_iter", None)
            if callable(scan_iter):
                return [self._decode_key(key) for key in scan_iter(match=pattern)]
            keys = getattr(client, "keys", None)
            if callable(keys):
                return [self._decode_key(key) for key in keys(pattern)]
        except Exception:
            self._disabled_after_error = True
        return []

    @staticmethod
    def _parse_key_date_range(key: str) -> tuple[date, date] | None:
        parts = key.rsplit(":", 2)
        if len(parts) != 3:
            return None
        try:
            return date.fromisoformat(parts[1]), date.fromisoformat(parts[2])
        except ValueError:
            return None

    @staticmethod
    def _decode_key(key: object) -> str:
        if isinstance(key, bytes):
            return key.decode("utf-8")
        return str(key)

    def _set_json(self, key: str, value: object, ttl_seconds: int) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            client.setex(key, max(1, int(ttl_seconds)), json.dumps(value, ensure_ascii=False))
        except Exception:
            self._disabled_after_error = True
