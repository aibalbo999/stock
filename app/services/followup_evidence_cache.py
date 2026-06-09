from __future__ import annotations

from app.db.session import session_scope
from app.services.company_filing_repository import CompanyFilingRepository
from app.services.followup_completion import _matched_target_item_count
from app.services.followup_evidence_queries import dedupe_terms
from app.services.ingestion import IngestionPipeline
from app.services.news_repository import NewsRepository


def cached_follow_up_news_items(
    pipeline: IngestionPipeline,
    target_tickers: list[str],
    target_terms: list[str],
    limit: int,
) -> list[dict]:
    mapper = getattr(pipeline, "mapper", None)
    if mapper is None:
        return []
    queries = dedupe_terms([*target_tickers, *target_terms], limit=8)
    if not queries:
        return []
    try:
        with session_scope() as session:
            repository = NewsRepository(session)
            filing_repository = CompanyFilingRepository(session)
            documents = []
            for query in queries:
                documents.extend(repository.search_documents(query, limit=max(5, limit)))
                filing_documents = filing_repository.search_documents(
                    query,
                    tickers=target_tickers or None,
                    limit=max(5, limit),
                )
                documents.extend(
                    CompanyFilingRepository.to_news_document(document)
                    for document in filing_documents
                )
    except Exception:
        return []
    deduped_documents = IngestionPipeline._dedupe_documents(documents)
    items = []
    for document in deduped_documents[: max(5, limit * 2)]:
        matches = mapper.match_document(document)
        items.append(
            {
                "id": document.id,
                "title": document.title,
                "publisher": document.source.publisher,
                "published_at": document.source.published_at.isoformat()
                if document.source.published_at
                else None,
                "url": document.source.url,
                "excerpt": document.text[:500],
                "entity_matches": [match.model_dump(mode="json") for match in matches],
            }
        )
    return filter_follow_up_target_items(items, target_tickers, target_terms)[:limit]


def dedupe_follow_up_items(items: list) -> list[dict]:
    return list(
        {
            item.get("id") or item.get("url") or item.get("title"): item
            for item in items
            if isinstance(item, dict)
        }.values()
    )


def filter_follow_up_target_items(
    items: list[dict],
    target_tickers: list[str],
    target_terms: list[str],
) -> list[dict]:
    if not target_tickers and not target_terms:
        return items
    return [
        item
        for item in items
        if _matched_target_item_count([item], target_tickers, target_terms) > 0
    ]


def has_follow_up_target_match(
    items: list[dict], target_tickers: list[str], target_terms: list[str]
) -> bool:
    if not items:
        return False
    if not target_tickers and not target_terms:
        return True
    return _matched_target_item_count(items, target_tickers, target_terms) > 0
