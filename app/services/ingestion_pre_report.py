from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from app.core.time import today_taipei
from app.models.schemas import ReportRequest


async def pre_report_refresh_for_pipeline(
    pipeline: Any,
    request: ReportRequest,
    *,
    today_func: Callable[[], date] = today_taipei,
) -> dict:
    pipeline._check_cancelled()
    end_date = today_func()
    start_date = end_date - timedelta(days=request.lookback_days)
    tickers = pipeline.mapper.filter_allowed_tickers(request.tickers)
    if not tickers:
        tickers = sorted(pipeline.mapper.whitelist.allowed_tickers())
    news = await pipeline.ingest_feeds(
        enabled_sources_only=True,
        topic=request.topic,
        limit=max(10, min(30, request.evidence_limit // 4)),
        start_date=start_date,
        end_date=end_date,
    )
    pipeline._check_cancelled()
    market = await pipeline.refresh_market(tickers, start_date, end_date)
    pipeline._check_cancelled()
    monthly_revenue = await pipeline.refresh_monthly_revenue(
        tickers,
        end_date - timedelta(days=450),
        end_date,
    )
    pipeline._check_cancelled()
    financial_metrics = await pipeline.refresh_financial_metrics(
        tickers,
        end_date - timedelta(days=365 * 6),
        end_date,
    )
    pipeline._check_cancelled()
    valuations = await pipeline.refresh_valuations(
        tickers,
        start_date,
        end_date,
    )
    pipeline._check_cancelled()
    company_filings = await pipeline.ingest_company_filings(
        tickers,
        limit_per_query=2,
        filter_allowed=False,
    )
    return {
        "news": news,
        "market": market,
        "monthly_revenue": monthly_revenue,
        "financial_metrics": financial_metrics,
        "valuations": valuations,
        "company_filings": company_filings,
    }
