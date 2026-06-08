from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.data_sources.market import MarketFetchError
from app.models.schemas import FinancialMetric, MarketSnapshot, MonthlyRevenue, ValuationMetric


def json_safe(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def market_data_payload(market_data: dict) -> dict:
    return {
        "snapshots": json_safe(market_data.get("snapshots") or []),
        "price_history_snapshots": json_safe(market_data.get("price_history_snapshots") or []),
        "market_errors": json_safe(market_data.get("market_errors") or []),
        "monthly_revenues": json_safe(market_data.get("monthly_revenues") or []),
        "monthly_revenue_errors": json_safe(market_data.get("monthly_revenue_errors") or []),
        "latest_monthly_revenues": json_safe(market_data.get("latest_monthly_revenues") or []),
        "financial_metrics": json_safe(market_data.get("financial_metrics") or []),
        "financial_metric_errors": json_safe(market_data.get("financial_metric_errors") or []),
        "valuations": json_safe(market_data.get("valuations") or []),
        "valuation_errors": json_safe(market_data.get("valuation_errors") or []),
    }


def market_data_from_payload(payload: dict) -> dict:
    return {
        "snapshots": [MarketSnapshot.model_validate(item) for item in payload.get("snapshots") or []],
        "price_history_snapshots": [
            MarketSnapshot.model_validate(item) for item in payload.get("price_history_snapshots") or []
        ],
        "market_errors": [MarketFetchError(**item) for item in payload.get("market_errors") or []],
        "monthly_revenues": [
            MonthlyRevenue.model_validate(item) for item in payload.get("monthly_revenues") or []
        ],
        "monthly_revenue_errors": [
            MarketFetchError(**item) for item in payload.get("monthly_revenue_errors") or []
        ],
        "latest_monthly_revenues": [
            MonthlyRevenue.model_validate(item) for item in payload.get("latest_monthly_revenues") or []
        ],
        "financial_metrics": [
            FinancialMetric.model_validate(item) for item in payload.get("financial_metrics") or []
        ],
        "financial_metric_errors": [
            MarketFetchError(**item) for item in payload.get("financial_metric_errors") or []
        ],
        "valuations": [ValuationMetric.model_validate(item) for item in payload.get("valuations") or []],
        "valuation_errors": [MarketFetchError(**item) for item in payload.get("valuation_errors") or []],
    }
