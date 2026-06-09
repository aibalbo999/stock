from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.data_sources.company_filing_discovery import is_relevant_company_filing_result
from app.data_sources.company_filing_http import company_filing_error
from app.models.schemas import CompanyFilingDocument, NewsDocument


FetchDocuments = Callable[..., Awaitable[tuple[list[CompanyFilingDocument], list[dict]]]]
GoogleNewsUrls = Callable[..., list[str]]
FetchFeed = Callable[..., Awaitable[list[NewsDocument]]]
BuildDocument = Callable[..., CompanyFilingDocument]


async def fetch_company_filing_discovery_documents(
    *,
    ticker: str,
    company_name: str,
    limit_per_query: int,
    document_types: list[str] | tuple[str, ...] | None,
    fetch_structured_api_documents_func: FetchDocuments,
    fetch_material_information_documents_func: FetchDocuments,
    google_news_urls_func: GoogleNewsUrls,
    fetch_feed_func: FetchFeed,
    build_news_document_func: BuildDocument,
) -> tuple[list[CompanyFilingDocument], list[dict]]:
    documents: list[CompanyFilingDocument] = []
    errors = []
    structured_documents, structured_errors = await fetch_structured_api_documents_func(
        ticker,
        company_name,
        limit=limit_per_query,
        document_types=document_types,
    )
    documents.extend(structured_documents)
    errors.extend(structured_errors)
    material_documents, material_errors = await fetch_material_information_documents_func(
        ticker,
        company_name,
        limit=limit_per_query,
        document_types=document_types,
    )
    documents.extend(material_documents)
    errors.extend(material_errors)
    for url in google_news_urls_func(ticker, company_name, document_types=document_types):
        try:
            feed_documents = await fetch_feed_func(
                url,
                publisher="Google News company filings",
                limit=limit_per_query,
            )
        except Exception as exc:
            errors.append(company_filing_error(url, exc, stage="discovery_feed"))
            continue
        for document in feed_documents:
            if not is_relevant_company_filing_result(document, ticker, company_name):
                continue
            documents.append(build_news_document_func(document, ticker, company_name))
    return documents, errors
