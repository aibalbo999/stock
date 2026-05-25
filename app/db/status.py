from __future__ import annotations

from sqlalchemy import func, inspect, select

from app.core.config import get_settings
from app.db.models import (
    AnalysisRun,
    CompanyFiling,
    FinancialMetricSnapshot,
    GeneratedReport,
    MonthlyRevenueSnapshot,
    NewsArticle,
    RiskClassificationCache,
    StockPriceSnapshot,
    ValuationMetricSnapshot,
)
from app.db.session import engine, session_scope
from app.services.persistence import AnalysisRunRepository


TABLE_MODELS = {
    "news_articles": NewsArticle,
    "company_filings": CompanyFiling,
    "generated_reports": GeneratedReport,
    "stock_price_snapshots": StockPriceSnapshot,
    "monthly_revenue_snapshots": MonthlyRevenueSnapshot,
    "financial_metric_snapshots": FinancialMetricSnapshot,
    "valuation_metric_snapshots": ValuationMetricSnapshot,
    "risk_classification_cache": RiskClassificationCache,
    "analysis_runs": AnalysisRun,
}


def db_status() -> dict:
    settings = get_settings()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    tables = {}
    with session_scope() as session:
        for table_name, model in TABLE_MODELS.items():
            exists = table_name in existing_tables
            count = session.scalar(select(func.count()).select_from(model)) if exists else None
            tables[table_name] = {"exists": exists, "count": count}
        orphan_run_count = (
            len(AnalysisRunRepository(session).orphan_report_ids())
            if "analysis_runs" in existing_tables and "generated_reports" in existing_tables
            else None
        )
    return {
        "database_url": _redact_database_url(settings.database_url),
        "tables": tables,
        "integrity": {"orphan_run_report_refs": orphan_run_count},
        "settings": {
            "whitelist_exists": settings.whitelist_path.exists(),
            "schedule_config_exists": settings.schedule_config_path.exists(),
            "news_sources_exists": settings.news_sources_path.exists(),
            "gemini_key_count": len(settings.gemini_api_keys),
            "use_chroma": settings.use_chroma,
        },
    }


def _redact_database_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    _, host = rest.rsplit("@", 1)
    return f"{scheme}://***@{host}"
