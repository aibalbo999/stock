from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    entity_matches_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CompanyFiling(Base):
    __tablename__ = "company_filings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    tickers_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    findings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class StockPriceSnapshot(Base):
    __tablename__ = "stock_price_snapshots"
    __table_args__ = (UniqueConstraint("ticker", "trade_date", name="uq_stock_price_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trading_volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trading_money: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trading_turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="FinMind TaiwanStockPrice")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MonthlyRevenueSnapshot(Base):
    __tablename__ = "monthly_revenue_snapshots"
    __table_args__ = (UniqueConstraint("ticker", "revenue_date", name="uq_monthly_revenue_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    revenue_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    revenue: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue_year: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue_month: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="FinMind TaiwanStockMonthRevenue")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class FinancialMetricSnapshot(Base):
    __tablename__ = "financial_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "report_date",
            "statement_type",
            "metric",
            name="uq_financial_metric_ticker_date_statement_metric",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    statement_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    origin_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ValuationMetricSnapshot(Base):
    __tablename__ = "valuation_metric_snapshots"
    __table_args__ = (UniqueConstraint("ticker", "trade_date", name="uq_valuation_metric_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    pe_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pb_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="FinMind TaiwanStockPER")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class RiskClassificationCache(Base):
    __tablename__ = "risk_classification_cache"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
