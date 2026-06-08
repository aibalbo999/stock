from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, timedelta
from typing import Protocol

from app.core.time import today_taipei
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.persistence import (
    CompanyFilingRepository,
)
from app.services.report_quality import is_stale_market_data_source


TRACKING_FRESHNESS_THRESHOLDS = {
    "refresh_market": 5,
    "refresh_monthly_revenue": 75,
    "refresh_valuations": 14,
    "refresh_financial_metrics": 150,
    "ingest_company_filings": 365,
}


class FollowUpFreshnessAction(Protocol):
    action_type: str
    purpose: str
    reason: str
    tickers: tuple[str, ...]

    def key(self) -> tuple[str, tuple[str, ...]]: ...

    def to_dict(self) -> dict: ...


SessionScopeFactory = Callable[[], AbstractContextManager]
TodayProvider = Callable[[], date]
FreshnessDetailsFunc = Callable[
    [list[FollowUpFreshnessAction], ReportRequest], dict[tuple[str, tuple[str, ...]], dict]
]


def filter_fresh_tracking_actions(
    actions: list[FollowUpFreshnessAction],
    request: ReportRequest,
    *,
    split_func: Callable[
        [list[FollowUpFreshnessAction], ReportRequest],
        tuple[list[FollowUpFreshnessAction], list[dict]],
    ]
    | None = None,
) -> list[FollowUpFreshnessAction]:
    if not actions:
        return []
    split_func = split_func or split_fresh_tracking_actions
    filtered, _ = split_func(actions, request)
    return filtered


def skipped_fresh_tracking_actions(
    actions: list[FollowUpFreshnessAction],
    request: ReportRequest,
    *,
    freshness_details_func: FreshnessDetailsFunc | None = None,
) -> list[FollowUpFreshnessAction]:
    freshness_details_func = freshness_details_func or tracking_freshness_details_by_action
    freshness = freshness_details_func(actions, request)
    return [
        action
        for action in actions
        if action.purpose == "tracking"
        and action.action_type != "rerun_analysis"
        and freshness.get(action.key(), {}).get("is_fresh", False)
    ]


def tracking_freshness_by_action(
    actions: list[FollowUpFreshnessAction],
    request: ReportRequest,
    *,
    freshness_details_func: FreshnessDetailsFunc | None = None,
) -> dict[tuple[str, tuple[str, ...]], bool]:
    freshness_details_func = freshness_details_func or tracking_freshness_details_by_action
    return {
        key: bool(value.get("is_fresh"))
        for key, value in freshness_details_func(actions, request).items()
    }


def tracking_freshness_details_by_action(
    actions: list[FollowUpFreshnessAction],
    request: ReportRequest,
    *,
    session_scope_func: SessionScopeFactory = session_scope,
    today_func: TodayProvider = today_taipei,
    thresholds: dict[str, int] | None = None,
) -> dict[tuple[str, tuple[str, ...]], dict]:
    thresholds = thresholds or TRACKING_FRESHNESS_THRESHOLDS
    today = today_func()
    tracking_actions = [
        action
        for action in actions
        if action.purpose == "tracking" and action.action_type != "rerun_analysis"
    ]
    if not tracking_actions:
        return {}
    tickers = sorted(
        {
            ticker
            for action in tracking_actions
            for ticker in (action.tickers or tuple(request.tickers))
        }
    )
    if not tickers:
        return {}
    try:
        with session_scope_func() as session:
            market_items = MarketRepository(session).latest_by_tickers(tickers)
            latest_market = {item.ticker: item.trade_date for item in market_items}
            stale_market = {
                item.ticker: item.source
                for item in market_items
                if is_stale_market_data_source(item.source)
            }
            revenue_items = MonthlyRevenueRepository(session).latest_by_tickers(tickers)
            latest_revenue = {item.ticker: item.revenue_date for item in revenue_items}
            stale_revenue = {
                item.ticker: item.source
                for item in revenue_items
                if is_stale_market_data_source(item.source)
            }
            valuation_items = ValuationMetricRepository(session).latest_by_tickers(tickers)
            latest_valuation = {item.ticker: item.trade_date for item in valuation_items}
            stale_valuation = {
                item.ticker: item.source
                for item in valuation_items
                if is_stale_market_data_source(item.source)
            }
            latest_company_filing = {}
            for ticker in tickers:
                stats = CompanyFilingRepository(session).stats_by_ticker(ticker)
                if stats.get("latest_date"):
                    latest_company_filing[ticker] = date.fromisoformat(stats["latest_date"])
            metrics = FinancialMetricRepository(session).by_tickers(tickers)
            latest_financial: dict[str, object] = {}
            latest_financial_source: dict[str, str] = {}
            for metric in metrics:
                current = latest_financial.get(metric.ticker)
                if current is None or metric.report_date > current:
                    latest_financial[metric.ticker] = metric.report_date
                    latest_financial_source[metric.ticker] = metric.source
            stale_financial = {
                ticker: source
                for ticker, source in latest_financial_source.items()
                if is_stale_market_data_source(source)
            }
    except Exception:
        return {}
    freshness = {}
    threshold_sources = {
        "refresh_market": (latest_market, thresholds["refresh_market"], stale_market),
        "refresh_monthly_revenue": (
            latest_revenue,
            thresholds["refresh_monthly_revenue"],
            stale_revenue,
        ),
        "refresh_valuations": (latest_valuation, thresholds["refresh_valuations"], stale_valuation),
        "refresh_financial_metrics": (
            latest_financial,
            thresholds["refresh_financial_metrics"],
            stale_financial,
        ),
        "ingest_company_filings": (latest_company_filing, thresholds["ingest_company_filings"], {}),
    }
    for action in tracking_actions:
        source = threshold_sources.get(action.action_type)
        if source is None:
            freshness[action.key()] = {
                "is_fresh": False,
                "max_age_days": None,
                "latest_dates": {},
            }
            continue
        latest_by_ticker, max_age_days, stale_by_ticker = source
        action_tickers = action.tickers or tuple(request.tickers)
        latest_dates = {
            ticker: latest_by_ticker[ticker].isoformat()
            for ticker in action_tickers
            if ticker in latest_by_ticker
        }
        stale_sources = {
            ticker: stale_by_ticker[ticker]
            for ticker in action_tickers
            if ticker in stale_by_ticker
        }
        freshness[action.key()] = {
            "is_fresh": bool(action_tickers)
            and all(
                ticker in latest_by_ticker
                and latest_by_ticker[ticker] >= today - timedelta(days=max_age_days)
                for ticker in action_tickers
            )
            and not stale_sources,
            "max_age_days": max_age_days,
            "latest_dates": latest_dates,
            "has_stale_sources": bool(stale_sources),
            "stale_sources": stale_sources,
        }
    return freshness


def skipped_fresh_tracking_details(
    actions: list[FollowUpFreshnessAction], request: ReportRequest
) -> list[dict]:
    _, rows = split_fresh_tracking_actions(actions, request)
    return rows


def split_fresh_tracking_actions(
    actions: list[FollowUpFreshnessAction],
    request: ReportRequest,
    *,
    freshness_details_func: FreshnessDetailsFunc | None = None,
) -> tuple[list[FollowUpFreshnessAction], list[dict]]:
    freshness_details_func = freshness_details_func or tracking_freshness_details_by_action
    freshness = freshness_details_func(actions, request)
    rows = []
    filtered = []
    for action in actions:
        details = freshness.get(action.key()) or {}
        if (
            action.purpose == "tracking"
            and action.action_type != "rerun_analysis"
            and details.get("is_fresh")
        ):
            rows.append({**action.to_dict(), "freshness": details})
            continue
        filtered.append(action)
    has_tracking_work = any(
        action.purpose == "tracking" and action.action_type != "rerun_analysis"
        for action in filtered
    )
    has_required_work = any(
        action.purpose == "required" and action.action_type != "rerun_analysis"
        for action in filtered
    )
    filtered = [
        action
        for action in filtered
        if action.action_type != "rerun_analysis"
        or (action.purpose == "tracking" and has_tracking_work)
        or (action.purpose == "required" and has_required_work)
        or (action.purpose == "required" and "LLM" in action.reason)
    ]
    return filtered, rows
