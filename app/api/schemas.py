from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


class ManualNewsIngest(BaseModel):
    title: str
    text: str
    publisher: str = "manual"
    published_at: Optional[date] = None
    url: Optional[str] = None


class ManualCompanyFilingIngest(BaseModel):
    ticker: str
    title: str
    text: str
    company_name: str = ""
    document_type: str = "company_disclosure"
    publisher: str = "manual company filing"
    published_at: Optional[date] = None
    url: Optional[str] = None


class CompanyFilingUrlIngest(BaseModel):
    ticker: str
    url: str
    company_name: str = ""
    document_type: str = "company_disclosure"
    publisher: Optional[str] = None
    published_at: Optional[date] = None


class MarketRefreshRequest(BaseModel):
    tickers: list[str] = []
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class FeedFetchRequest(BaseModel):
    url: Optional[str] = None
    publisher: Optional[str] = None
    limit: int = 10
    enabled_sources_only: bool = True
    topic: Optional[str] = None


class MaintenanceCleanupRequest(BaseModel):
    failed_runs: bool = False
    orphan_report_refs: bool = False
    latest_reports_only: bool = False
    stale_running_before: Optional[datetime] = None
    runs_before: Optional[datetime] = None
    reports_before: Optional[datetime] = None


class DataOperationTaskRequest(BaseModel):
    operation: Literal[
        "market_refresh",
        "fundamentals_refresh",
        "valuation_refresh",
        "company_filings_fetch",
        "company_filing_from_url",
        "feed_fetch",
    ]
    payload: dict[str, Any] = {}


class ReportFollowUpTaskRequest(BaseModel):
    rerun_report: bool = True
    news_limit: int = 30
    purpose: Literal["all", "required", "tracking"] = "all"
    record_noop: bool = False
    force_refresh: bool = False


class FollowUpRunRequest(BaseModel):
    rerun_report: bool = True
    news_limit: int = 30
    purpose: Literal["all", "required", "tracking"] = "all"
    record_noop: bool = False
    force_refresh: bool = False


class TopicDiscoveryRequest(BaseModel):
    topic: str = "AI 產業鏈"
    limit_per_query: int = 5
    lookback_days: int = 14
    evidence_limit: int = 40
    analysis_mode: Literal["fast", "standard", "deep"] = "standard"
    deep_analysis: bool = False
    include_international: bool = True
    investor_capital: int = 1_000_000
    beginner_mode: bool = True
    investor_profile: str = "beginner"
    max_position_pct: float = 0.10
    cash_reserve_pct: float = 0.30
