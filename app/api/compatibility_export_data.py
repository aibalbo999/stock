from __future__ import annotations

# ruff: noqa: F401

from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    filing_quality_score,
    filing_source_tier,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.rag.vector_store import VectorStore
from app.services.candidate_audit import (
    candidate_audit_summary,
    render_candidate_audit_markdown,
)
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.company_data_audit import audit_company_data, audit_report_company_data
from app.services.company_data_audit_api import (
    CompanyDataAuditApiNotFound,
    CompanyDataAuditApiService,
)
from app.services.company_filing_api import CompanyFilingApiService
from app.services.data_operations_api import DataOperationsApiService
from app.services.ingestion import IngestionPipeline
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.persistence import (
    AnalysisRunRepository,
    CompanyFilingRepository,
    LLMUsageRepository,
    NewsRepository,
    ReportRepository,
)
from app.services.source_quality import (
    filter_formal_evidence_documents,
    remove_low_quality_investor_forum_lines,
)
from app.services.source_relevance import SourceRelevanceAnalyzer

DATA_EXPORT_NAMES = (
    "CompanyFilingFetcher",
    "filing_quality_score",
    "filing_source_tier",
    "MarketDataClient",
    "NewsFetcher",
    "NewsSourceStore",
    "VectorStore",
    "candidate_audit_summary",
    "render_candidate_audit_markdown",
    "audit_company_data",
    "audit_report_company_data",
    "CompanyDataAuditApiService",
    "CompanyDataAuditApiNotFound",
    "CompanyFilingApiService",
    "DataOperationsApiService",
    "CandidateRevalidationService",
    "IngestionPipeline",
    "AnalysisRunRepository",
    "CompanyFilingRepository",
    "FinancialMetricRepository",
    "LLMUsageRepository",
    "MarketRepository",
    "MonthlyRevenueRepository",
    "NewsRepository",
    "ReportRepository",
    "ValuationMetricRepository",
    "filter_formal_evidence_documents",
    "remove_low_quality_investor_forum_lines",
    "SourceRelevanceAnalyzer",
)


def compatibility_data_export_namespace() -> dict[str, object]:
    return {name: globals()[name] for name in DATA_EXPORT_NAMES}
