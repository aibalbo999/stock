from __future__ import annotations

from collections.abc import Iterable

from app.models.schemas import EntityMatch, NewsDocument
from app.services import report_early_potential
from app.services.entity_mapping import EntityMapper
from app.services.source_quality import filter_formal_evidence_documents
from app.services.whitelist import SupplyChainWhitelist


DocumentMatchCache = dict[tuple[str, str, str, int], list[EntityMatch]]


def document_matches(
    document: NewsDocument,
    *,
    mapper: EntityMapper,
    whitelist: SupplyChainWhitelist,
    cache: DocumentMatchCache,
) -> list[EntityMatch]:
    key = document_match_cache_key(document)
    if key not in cache:
        metadata_matches = document_metadata_matches(document, whitelist)
        cache[key] = metadata_matches or mapper.match_document(document)
    return cache[key]


def document_match_cache_key(document: NewsDocument) -> tuple[str, str, str, int]:
    return (
        document.id or "",
        document.source.url or "",
        document.title,
        len(document.text or ""),
    )


def document_metadata_matches(
    document: NewsDocument,
    whitelist: SupplyChainWhitelist,
) -> list[EntityMatch]:
    tickers = set(document.entity_tickers)
    if not tickers:
        return []
    matches = []
    for segment in whitelist.segments:
        for company in segment.companies:
            if company.ticker not in tickers:
                continue
            matches.append(
                EntityMatch(
                    ticker=company.ticker,
                    name=company.name,
                    segment_id=segment.id,
                    segment_name=segment.name,
                    matched_alias="metadata",
                )
            )
    return matches


def related_documents(
    ticker: str,
    documents: list[NewsDocument],
    *,
    document_match_resolver,
) -> list[NewsDocument]:
    documents = filter_formal_evidence_documents(documents)
    return [
        document
        for document in documents
        if any(match.ticker == ticker for match in document_match_resolver(document))
    ]


def document_company_labels(document: NewsDocument, *, document_match_resolver) -> list[str]:
    try:
        return [f"{match.ticker} {match.name}" for match in document_match_resolver(document)]
    except Exception:
        return []


def candidate_audit_evidence_counts(candidate_audit: Iterable[dict]) -> dict[str, dict[str, int]]:
    return report_early_potential.candidate_audit_evidence_counts(candidate_audit)


def publisher_count(documents: list[NewsDocument]) -> int:
    return report_early_potential.publisher_count(documents)
