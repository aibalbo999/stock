"""Initial application schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("output_path", sa.String(length=1000), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "company_filings",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_filings_document_type", "company_filings", ["document_type"])
    op.create_index("ix_company_filings_ticker", "company_filings", ["ticker"])
    op.create_table(
        "financial_metric_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("statement_type", sa.String(length=60), nullable=False),
        sa.Column("metric", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("origin_name", sa.String(length=300), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker",
            "report_date",
            "statement_type",
            "metric",
            name="uq_financial_metric_ticker_date_statement_metric",
        ),
    )
    op.create_index("ix_financial_metric_snapshots_metric", "financial_metric_snapshots", ["metric"])
    op.create_index("ix_financial_metric_snapshots_report_date", "financial_metric_snapshots", ["report_date"])
    op.create_index("ix_financial_metric_snapshots_statement_type", "financial_metric_snapshots", ["statement_type"])
    op.create_index("ix_financial_metric_snapshots_ticker", "financial_metric_snapshots", ["ticker"])
    op.create_table(
        "generated_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("tickers_json", sa.Text(), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "monthly_revenue_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("revenue_date", sa.Date(), nullable=False),
        sa.Column("revenue", sa.Integer(), nullable=False),
        sa.Column("revenue_year", sa.Integer(), nullable=False),
        sa.Column("revenue_month", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "revenue_date", name="uq_monthly_revenue_ticker_date"),
    )
    op.create_index("ix_monthly_revenue_snapshots_revenue_date", "monthly_revenue_snapshots", ["revenue_date"])
    op.create_index("ix_monthly_revenue_snapshots_ticker", "monthly_revenue_snapshots", ["ticker"])
    op.create_table(
        "news_articles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("entity_matches_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "risk_classification_cache",
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("topic_hash", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("keywords_json", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("document_id", "topic_hash"),
    )
    op.create_table(
        "stock_price_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("trading_volume", sa.Integer(), nullable=True),
        sa.Column("trading_money", sa.Integer(), nullable=True),
        sa.Column("trading_turnover", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "trade_date", name="uq_stock_price_ticker_date"),
    )
    op.create_index("ix_stock_price_snapshots_ticker", "stock_price_snapshots", ["ticker"])
    op.create_index("ix_stock_price_snapshots_trade_date", "stock_price_snapshots", ["trade_date"])
    op.create_table(
        "valuation_metric_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("pe_ratio", sa.Float(), nullable=True),
        sa.Column("pb_ratio", sa.Float(), nullable=True),
        sa.Column("dividend_yield", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "trade_date", name="uq_valuation_metric_ticker_date"),
    )
    op.create_index("ix_valuation_metric_snapshots_ticker", "valuation_metric_snapshots", ["ticker"])
    op.create_index("ix_valuation_metric_snapshots_trade_date", "valuation_metric_snapshots", ["trade_date"])


def downgrade() -> None:
    op.drop_index("ix_valuation_metric_snapshots_trade_date", table_name="valuation_metric_snapshots")
    op.drop_index("ix_valuation_metric_snapshots_ticker", table_name="valuation_metric_snapshots")
    op.drop_table("valuation_metric_snapshots")
    op.drop_index("ix_stock_price_snapshots_trade_date", table_name="stock_price_snapshots")
    op.drop_index("ix_stock_price_snapshots_ticker", table_name="stock_price_snapshots")
    op.drop_table("stock_price_snapshots")
    op.drop_table("risk_classification_cache")
    op.drop_table("news_articles")
    op.drop_index("ix_monthly_revenue_snapshots_ticker", table_name="monthly_revenue_snapshots")
    op.drop_index("ix_monthly_revenue_snapshots_revenue_date", table_name="monthly_revenue_snapshots")
    op.drop_table("monthly_revenue_snapshots")
    op.drop_table("generated_reports")
    op.drop_index("ix_financial_metric_snapshots_ticker", table_name="financial_metric_snapshots")
    op.drop_index("ix_financial_metric_snapshots_statement_type", table_name="financial_metric_snapshots")
    op.drop_index("ix_financial_metric_snapshots_report_date", table_name="financial_metric_snapshots")
    op.drop_index("ix_financial_metric_snapshots_metric", table_name="financial_metric_snapshots")
    op.drop_table("financial_metric_snapshots")
    op.drop_index("ix_company_filings_ticker", table_name="company_filings")
    op.drop_index("ix_company_filings_document_type", table_name="company_filings")
    op.drop_table("company_filings")
    op.drop_table("analysis_runs")
