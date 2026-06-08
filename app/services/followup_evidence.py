from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Protocol

from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services.followup_completion import _matched_target_item_count
from app.services.followup_evidence_queries import (
    company_filing_document_types_from_reason as company_filing_document_types_from_reason,
    company_name_from_follow_up_reason as company_name_from_follow_up_reason,
    dedupe_terms as dedupe_terms,
    follow_up_fallback_topic as follow_up_fallback_topic,
    follow_up_news_queries as follow_up_news_queries,
    follow_up_target_terms as follow_up_target_terms,
    google_news_rss_url as google_news_rss_url,
    needs_company_filing_sources as needs_company_filing_sources,
)
from app.services.ingestion import IngestionPipeline
from app.services.persistence import CompanyFilingRepository, NewsRepository


FOLLOW_UP_NEWS_QUERY_TIMEOUT_SECONDS = 8
FOLLOW_UP_NEWS_FALLBACK_TIMEOUT_SECONDS = 20
FOLLOW_UP_NEWS_WEB_SEARCH_TIMEOUT_SECONDS = 30


class FollowUpEvidenceAction(Protocol):
    reason: str
    tickers: tuple[str, ...]


async def ingest_follow_up_news(
    pipeline: IngestionPipeline,
    action: FollowUpEvidenceAction,
    request: ReportRequest,
    news_limit: int,
    today,
) -> dict:
    start_date = today - timedelta(days=max(request.lookback_days, 30))
    queries = follow_up_news_queries(action, request)
    if not queries:
        return await pipeline.ingest_feeds(
            enabled_sources_only=True,
            topic=request.topic,
            limit=news_limit,
            start_date=start_date,
            end_date=today,
        )

    per_query_limit = max(3, min(10, news_limit // max(1, len(queries))))
    results = []
    items = []
    errors = []
    target_terms = follow_up_target_terms(action)
    target_tickers = list(action.tickers)
    cached_items = cached_follow_up_news_items(pipeline, target_tickers, target_terms, news_limit)
    if _has_follow_up_target_match(cached_items, target_tickers, target_terms):
        return {
            "count": len(cached_items),
            "items": cached_items,
            "errors": [],
            "suppressed_errors": [],
            "queries": [],
            "web_search": None,
            "fallback": None,
            "target_terms": target_terms,
            "source": "cached follow-up news evidence",
        }
    semaphore = asyncio.Semaphore(4)

    async def fetch_query(query: str) -> tuple[dict, dict]:
        url = google_news_rss_url(query)
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    pipeline.ingest_feeds(
                        url=url,
                        publisher="Google News follow-up",
                        limit=per_query_limit,
                        enabled_sources_only=False,
                        start_date=start_date,
                        end_date=today,
                    ),
                    timeout=FOLLOW_UP_NEWS_QUERY_TIMEOUT_SECONDS,
                )
        except Exception as exc:
            result = {
                "count": 0,
                "items": [],
                "errors": [{"source": url, "error": str(exc) or exc.__class__.__name__}],
            }
        return result, {
            "query": query,
            "url": url,
            "count": result.get("count", 0),
            "errors": result.get("errors", []),
        }

    for result, query_result in await asyncio.gather(*(fetch_query(query) for query in queries)):
        results.append(query_result)
        items.extend(result.get("items", []) or [])
        errors.extend(result.get("errors", []) or [])
    deduped_items = filter_follow_up_target_items(
        dedupe_follow_up_items(items),
        target_tickers,
        target_terms,
    )
    fallback = None
    coverage_fallback_count = 0
    suppressed_errors = []
    if coverage_fallback_count <= 0 and not _has_follow_up_target_match(deduped_items, target_tickers, target_terms):
        google_errors = list(errors)
        fallback_topic = follow_up_fallback_topic(action, request)
        try:
            fallback = await asyncio.wait_for(
                pipeline.ingest_feeds(
                    enabled_sources_only=True,
                    topic=fallback_topic,
                    limit=news_limit,
                    start_date=start_date,
                    end_date=today,
                ),
                timeout=FOLLOW_UP_NEWS_FALLBACK_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            fallback = {
                "count": 0,
                "items": [],
                "errors": [{"source": fallback_topic, "error": str(exc) or exc.__class__.__name__}],
            }
        items.extend(fallback.get("items", []) or [])
        fallback_errors = fallback.get("errors", []) or []
        errors = fallback_errors if fallback.get("items") else [*google_errors, *fallback_errors]
        suppressed_errors = google_errors if fallback.get("items") else []
        deduped_items = filter_follow_up_target_items(
            dedupe_follow_up_items(items),
            target_tickers,
            target_terms,
        )
        if not target_tickers and not deduped_items and fallback.get("items"):
            fallback_items = dedupe_follow_up_items(fallback.get("items") or [])
            coverage_fallback_count = len(fallback_items)
            deduped_items = fallback_items[:news_limit]
    web_search = None
    if coverage_fallback_count <= 0 and not _has_follow_up_target_match(deduped_items, target_tickers, target_terms):
        prior_errors = list(errors)
        try:
            web_search = await asyncio.wait_for(
                pipeline.ingest_web_search(
                    queries=queries,
                    topic=follow_up_fallback_topic(action, request),
                    limit_per_query=max(2, min(5, news_limit // max(1, len(queries)))),
                    start_date=start_date,
                    end_date=today,
                    target_terms=target_terms,
                ),
                timeout=FOLLOW_UP_NEWS_WEB_SEARCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            web_search = {
                "count": 0,
                "items": [],
                "errors": [{"source": "targeted web search", "error": str(exc) or exc.__class__.__name__}],
                "queries": [],
                "target_terms": target_terms,
            }
        items.extend(web_search.get("items", []) or [])
        web_errors = web_search.get("errors", []) or []
        if web_search.get("items"):
            suppressed_errors.extend(prior_errors)
            errors = web_errors
        else:
            errors.extend(web_errors)
        deduped_items = filter_follow_up_target_items(
            dedupe_follow_up_items(items),
            target_tickers,
            target_terms,
        )
    source_parts = ["Google News targeted follow-up"]
    if fallback:
        source_parts.append("enabled-source fallback")
    if web_search:
        source_parts.append("targeted web search")
    return {
        "count": len(deduped_items),
        "items": deduped_items,
        "errors": errors,
        "suppressed_errors": suppressed_errors,
        "queries": results,
        "web_search": web_search,
        "fallback": fallback,
        "coverage_fallback_count": coverage_fallback_count,
        "target_terms": target_terms,
        "source": " + ".join(source_parts),
    }


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


def _has_follow_up_target_match(items: list[dict], target_tickers: list[str], target_terms: list[str]) -> bool:
    if not items:
        return False
    if not target_tickers and not target_terms:
        return True
    return _matched_target_item_count(items, target_tickers, target_terms) > 0
