from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str
    url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[date] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class NewsDocument(BaseModel):
    id: str
    title: str
    text: str
    source: Source


class Company(BaseModel):
    ticker: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    evidence_keywords: list[str] = Field(default_factory=list)


class SupplyChainSegment(BaseModel):
    id: str
    name: str
    companies: list[Company] = Field(default_factory=list)
    notes: Optional[str] = None


class EntityMatch(BaseModel):
    ticker: str
    name: str
    segment_id: str
    segment_name: str
    matched_alias: str


class RiskType(str, Enum):
    structural_bottleneck = "structural_bottleneck"
    short_term_volatility = "short_term_volatility"
    opportunity_or_growth = "opportunity_or_growth"
    insufficient_data = "insufficient_data"


class InvestorProfile(str, Enum):
    beginner = "beginner"
    balanced = "balanced"
    aggressive = "aggressive"


class RiskFinding(BaseModel):
    risk_type: RiskType
    topic: str
    evidence: str
    source: Source
    related_companies: list[EntityMatch] = Field(default_factory=list)


class MarketSnapshot(BaseModel):
    ticker: str
    trade_date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    spread: Optional[float] = None
    trading_volume: Optional[int] = None
    trading_money: Optional[int] = None
    trading_turnover: Optional[float] = None
    source: str = "FinMind TaiwanStockPrice"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class MonthlyRevenue(BaseModel):
    ticker: str
    revenue_date: date
    revenue: int
    revenue_year: int
    revenue_month: int
    yoy_pct: Optional[float] = None
    source: str = "FinMind TaiwanStockMonthRevenue"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class FinancialMetric(BaseModel):
    ticker: str
    report_date: date
    statement_type: str
    metric: str
    value: float
    origin_name: Optional[str] = None
    source: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class ValuationMetric(BaseModel):
    ticker: str
    trade_date: date
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    source: str = "FinMind TaiwanStockPER"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class ReportRequest(BaseModel):
    topic: str = "AI 產業鏈"
    tickers: list[str] = Field(default_factory=list)
    lookback_days: int = 14
    evidence_limit: int = Field(default=40, ge=20, le=200)
    investor_capital: int = Field(default=1_000_000, ge=10_000, le=100_000_000)
    beginner_mode: bool = True
    investor_profile: InvestorProfile = InvestorProfile.beginner
    max_position_pct: float = Field(default=0.10, ge=0.01, le=0.20)
    cash_reserve_pct: float = Field(default=0.30, ge=0.10, le=0.80)


class ReportResponse(BaseModel):
    title: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    markdown: str
    findings: list[RiskFinding] = Field(default_factory=list)
    quality_gate: Optional[dict] = None
