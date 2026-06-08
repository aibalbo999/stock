from __future__ import annotations

from collections.abc import Callable

from app.data_sources.company_filing_discovery import (
    HIGH_QUALITY_FILING_SCORE,
    REQUIRED_CORE_DOCUMENT_TYPES,
    filing_quality_score,
)
from app.models.schemas import NewsDocument
from app.services import report_company_narrative
from app.services.entity_mapping import company_filing_owner_ticker
from app.services.persistence import CompanyFilingRepository
from app.services.whitelist import SupplyChainWhitelist


def company_filing_missing(
    ticker: str,
    documents: list[NewsDocument],
    *,
    whitelist: SupplyChainWhitelist,
    session_scope_func: Callable,
) -> list[str]:
    companies = {company.ticker: company for company in whitelist.companies()}
    company = companies.get(ticker)
    company_name = company.name if company else ""
    high_quality_types: set[str] = set()

    for document in company_filing_documents_from_db(ticker, session_scope_func=session_scope_func):
        if filing_quality_score(document, ticker, company_name) >= HIGH_QUALITY_FILING_SCORE:
            high_quality_types.add(document.document_type)

    for document in documents:
        if not is_company_filing_document(ticker, document):
            continue
        document_type = news_document_filing_type(document)
        if document_type and filing_quality_score(document, ticker, company_name) >= HIGH_QUALITY_FILING_SCORE:
            high_quality_types.add(document_type)

    missing_required = [
        document_type
        for document_type in REQUIRED_CORE_DOCUMENT_TYPES
        if document_type not in high_quality_types
    ]
    if not missing_required:
        return []
    return ["缺公司公開文件（" + "、".join(filing_type_label(item) for item in missing_required) + "）"]


def filing_type_label(document_type: str) -> str:
    return report_company_narrative.filing_type_label(document_type)


def company_filing_documents_from_db(ticker: str, *, session_scope_func: Callable):
    try:
        with session_scope_func() as session:
            return CompanyFilingRepository(session).latest_by_tickers([ticker], limit_per_ticker=8)
    except Exception:
        return []


def is_company_filing_document(ticker: str, document: NewsDocument) -> bool:
    return company_filing_owner_ticker(document) == ticker


def news_document_filing_type(document: NewsDocument) -> str | None:
    return report_company_narrative.news_document_filing_type(document)
