from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.services.company_filing_results import (
    company_filing_attempt_result,
    enrich_company_filing_errors,
    missing_company_filing_document_types,
    should_broaden_company_filing_search,
    should_retry_company_filing_fetch,
)
from app.services.ingestion_documents import dedupe_documents


async def fetch_company_filing_ticker_documents(
    *,
    fetcher: Any,
    ticker: str,
    company_name: str,
    cached_documents: Sequence[Any],
    target_document_types: Sequence[str],
    document_types: list[str] | None,
    limit_per_query: int,
    check_cancelled: Callable[[], None],
) -> dict[str, Any]:
    target_types = list(target_document_types)
    company_documents = list(cached_documents)
    enriched_errors: list[dict] = []
    latest_errors: list[dict] = []
    attempts: list[dict] = []
    if cached_documents:
        attempts.append(
            company_filing_attempt_result(
                "cached_company_filings",
                cached_documents,
                [],
            )
        )

    mops_attempted = False
    if "annual_report" in _missing_document_types(company_documents, target_types):
        latest_errors = await _fetch_mops_annual_report(
            fetcher=fetcher,
            ticker=ticker,
            company_name=company_name,
            company_documents=company_documents,
            enriched_errors=enriched_errors,
            attempts=attempts,
            check_cancelled=check_cancelled,
        )
        mops_attempted = True

    if should_broaden_company_filing_search(company_documents, enriched_errors, target_types):
        latest_errors = await _fetch_discovery_documents(
            fetcher=fetcher,
            strategy="targeted_search",
            ticker=ticker,
            company_name=company_name,
            company_documents=company_documents,
            enriched_errors=enriched_errors,
            attempts=attempts,
            check_cancelled=check_cancelled,
            limit_per_query=limit_per_query,
            document_types=_missing_document_types(company_documents, target_types)
            or document_types,
        )

    if should_retry_company_filing_fetch(company_documents, latest_errors):
        latest_errors = await _fetch_discovery_documents(
            fetcher=fetcher,
            strategy="retry_after_source_error",
            ticker=ticker,
            company_name=company_name,
            company_documents=company_documents,
            enriched_errors=enriched_errors,
            attempts=attempts,
            check_cancelled=check_cancelled,
            limit_per_query=limit_per_query,
            document_types=_missing_document_types(company_documents, target_types)
            or document_types,
        )

    if should_broaden_company_filing_search(company_documents, enriched_errors, target_types):
        latest_errors = await _fetch_discovery_documents(
            fetcher=fetcher,
            strategy="broaden_official_search",
            ticker=ticker,
            company_name=company_name,
            company_documents=company_documents,
            enriched_errors=enriched_errors,
            attempts=attempts,
            check_cancelled=check_cancelled,
            limit_per_query=limit_per_query + 2,
            document_types=None,
        )

    if not mops_attempted and "annual_report" in _missing_document_types(
        company_documents, target_types
    ):
        latest_errors = await _fetch_mops_annual_report(
            fetcher=fetcher,
            ticker=ticker,
            company_name=company_name,
            company_documents=company_documents,
            enriched_errors=enriched_errors,
            attempts=attempts,
            check_cancelled=check_cancelled,
        )

    if should_broaden_company_filing_search(company_documents, enriched_errors, target_types):
        latest_errors = await _fetch_official_website_documents(
            fetcher=fetcher,
            ticker=ticker,
            company_name=company_name,
            company_documents=company_documents,
            enriched_errors=enriched_errors,
            attempts=attempts,
            check_cancelled=check_cancelled,
            limit=limit_per_query + 5,
            document_types=_missing_document_types(company_documents, target_types)
            or document_types,
        )

    if should_broaden_company_filing_search(company_documents, enriched_errors, target_types):
        await _fetch_web_search_documents(
            fetcher=fetcher,
            ticker=ticker,
            company_name=company_name,
            company_documents=company_documents,
            enriched_errors=enriched_errors,
            attempts=attempts,
            check_cancelled=check_cancelled,
            limit_per_query=limit_per_query + 3,
            document_types=_missing_document_types(company_documents, target_types)
            or document_types,
        )

    return {
        "documents": dedupe_documents(company_documents),
        "errors": enriched_errors,
        "attempts": attempts,
    }


async def _fetch_mops_annual_report(
    *,
    fetcher: Any,
    ticker: str,
    company_name: str,
    company_documents: list[Any],
    enriched_errors: list[dict],
    attempts: list[dict],
    check_cancelled: Callable[[], None],
) -> list[dict]:
    documents, raw_errors = await fetcher.fetch_mops_annual_report_documents(
        ticker,
        company_name,
    )
    check_cancelled()
    return _record_company_filing_attempt(
        strategy="mops_annual_report",
        ticker=ticker,
        company_name=company_name,
        fetched_documents=documents,
        raw_errors=raw_errors,
        company_documents=company_documents,
        enriched_errors=enriched_errors,
        attempts=attempts,
    )


async def _fetch_discovery_documents(
    *,
    fetcher: Any,
    strategy: str,
    ticker: str,
    company_name: str,
    company_documents: list[Any],
    enriched_errors: list[dict],
    attempts: list[dict],
    check_cancelled: Callable[[], None],
    limit_per_query: int,
    document_types: list[str] | None,
) -> list[dict]:
    documents, raw_errors = await fetcher.fetch_discovery_documents(
        ticker,
        company_name,
        limit_per_query=limit_per_query,
        document_types=document_types,
    )
    check_cancelled()
    return _record_company_filing_attempt(
        strategy=strategy,
        ticker=ticker,
        company_name=company_name,
        fetched_documents=documents,
        raw_errors=raw_errors,
        company_documents=company_documents,
        enriched_errors=enriched_errors,
        attempts=attempts,
    )


async def _fetch_official_website_documents(
    *,
    fetcher: Any,
    ticker: str,
    company_name: str,
    company_documents: list[Any],
    enriched_errors: list[dict],
    attempts: list[dict],
    check_cancelled: Callable[[], None],
    limit: int,
    document_types: list[str] | None,
) -> list[dict]:
    documents, raw_errors = await fetcher.fetch_official_website_documents(
        ticker,
        company_name,
        limit=limit,
        document_types=document_types,
    )
    check_cancelled()
    return _record_company_filing_attempt(
        strategy="official_company_website",
        ticker=ticker,
        company_name=company_name,
        fetched_documents=documents,
        raw_errors=raw_errors,
        company_documents=company_documents,
        enriched_errors=enriched_errors,
        attempts=attempts,
    )


async def _fetch_web_search_documents(
    *,
    fetcher: Any,
    ticker: str,
    company_name: str,
    company_documents: list[Any],
    enriched_errors: list[dict],
    attempts: list[dict],
    check_cancelled: Callable[[], None],
    limit_per_query: int,
    document_types: list[str] | None,
) -> list[dict]:
    documents, raw_errors = await fetcher.fetch_web_search_documents(
        ticker,
        company_name,
        limit_per_query=limit_per_query,
        document_types=document_types,
    )
    check_cancelled()
    return _record_company_filing_attempt(
        strategy="official_web_search",
        ticker=ticker,
        company_name=company_name,
        fetched_documents=documents,
        raw_errors=raw_errors,
        company_documents=company_documents,
        enriched_errors=enriched_errors,
        attempts=attempts,
    )


def _record_company_filing_attempt(
    *,
    strategy: str,
    ticker: str,
    company_name: str,
    fetched_documents: Sequence[Any],
    raw_errors: Sequence[dict],
    company_documents: list[Any],
    enriched_errors: list[dict],
    attempts: list[dict],
) -> list[dict]:
    attempt_errors = enrich_company_filing_errors(raw_errors, ticker, company_name)
    company_documents.extend(fetched_documents)
    enriched_errors.extend(attempt_errors)
    attempts.append(
        company_filing_attempt_result(
            strategy,
            fetched_documents,
            attempt_errors,
        )
    )
    return attempt_errors


def _missing_document_types(documents: Sequence[Any], target_document_types: Sequence[str]) -> list[str]:
    return missing_company_filing_document_types(
        documents,
        list(target_document_types),
    )


__all__ = ["fetch_company_filing_ticker_documents"]
