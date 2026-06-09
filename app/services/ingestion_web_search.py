from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, ContextManager

from app.data_sources.news import NewsFetcher


SearchFunc = Callable[[str, int], Awaitable[list[dict]]]
MatchesTargetTerms = Callable[[Any, list[str] | None], bool]
DedupeDocuments = Callable[[list[Any]], list[Any]]
FilterDocuments = Callable[[list[Any], date | None, date | None, bool], list[Any]]
SessionScope = Callable[[], ContextManager[Any]]
SEARCH_TIMEOUT_SECONDS = 10
FETCH_TIMEOUT_SECONDS = 8
FETCH_CONCURRENCY = 12


async def ingest_web_search_for_pipeline(
    *,
    queries: list[str],
    topic: str | None,
    limit_per_query: int,
    start_date: date | None,
    end_date: date | None,
    target_terms: list[str] | None,
    quality_filter: bool,
    mapper: Any,
    search_func: SearchFunc,
    matches_target_terms_func: MatchesTargetTerms,
    dedupe_documents_func: DedupeDocuments,
    filter_documents_func: FilterDocuments,
    news_fetcher_cls: type[NewsFetcher],
    vector_store_cls: type,
    session_scope_func: SessionScope,
    news_repository_cls: type,
) -> dict:
    fetcher = news_fetcher_cls()
    query_results = [{"query": query, "count": 0, "errors": []} for query in queries]
    search_payloads = await _search_queries(
        queries,
        search_func=search_func,
        limit_per_query=limit_per_query,
    )
    documents, errors = await _fetch_matching_search_documents(
        search_payloads,
        query_results=query_results,
        target_terms=target_terms,
        fetcher=fetcher,
        news_fetcher_cls=news_fetcher_cls,
        matches_target_terms_func=matches_target_terms_func,
    )
    documents = filter_documents_func(
        dedupe_documents_func(documents),
        start_date,
        end_date,
        quality_filter,
    )
    ingested = _persist_web_search_documents(
        documents,
        mapper=mapper,
        vector_store_cls=vector_store_cls,
        session_scope_func=session_scope_func,
        news_repository_cls=news_repository_cls,
    )
    return _web_search_result_payload(
        ingested=ingested,
        errors=errors,
        query_results=query_results,
        target_terms=target_terms,
        topic=topic,
        selected_count=len(queries),
    )


async def _search_queries(
    queries: list[str],
    *,
    search_func: SearchFunc,
    limit_per_query: int,
) -> list[tuple[int, str, list[dict], str | None]]:
    return await asyncio.gather(
        *(
            _search_query(index, query, search_func=search_func, limit_per_query=limit_per_query)
            for index, query in enumerate(queries)
        )
    )


async def _search_query(
    index: int,
    query: str,
    *,
    search_func: SearchFunc,
    limit_per_query: int,
) -> tuple[int, str, list[dict], str | None]:
    try:
        search_results = await asyncio.wait_for(
            search_func(query, limit_per_query),
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return index, query, [], str(exc) or exc.__class__.__name__
    return index, query, search_results, None


async def _fetch_matching_search_documents(
    search_payloads: list[tuple[int, str, list[dict], str | None]],
    *,
    query_results: list[dict],
    target_terms: list[str] | None,
    fetcher: Any,
    news_fetcher_cls: type[NewsFetcher],
    matches_target_terms_func: MatchesTargetTerms,
) -> tuple[list[Any], list[dict]]:
    errors = []
    fetch_tasks = []
    seen_urls: set[str] = set()
    fetch_semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    for payload in search_payloads:
        _queue_search_result_fetches(
            payload,
            query_results=query_results,
            errors=errors,
            fetch_tasks=fetch_tasks,
            seen_urls=seen_urls,
            target_terms=target_terms,
            fetcher=fetcher,
            fetch_semaphore=fetch_semaphore,
            news_fetcher_cls=news_fetcher_cls,
            matches_target_terms_func=matches_target_terms_func,
        )
    return await _collect_fetched_documents(fetch_tasks, errors=errors, query_results=query_results)


def _queue_search_result_fetches(
    payload: tuple[int, str, list[dict], str | None],
    *,
    query_results: list[dict],
    errors: list[dict],
    fetch_tasks: list[Awaitable[tuple[int, object | None, dict | None]]],
    seen_urls: set[str],
    target_terms: list[str] | None,
    fetcher: Any,
    fetch_semaphore: asyncio.Semaphore,
    news_fetcher_cls: type[NewsFetcher],
    matches_target_terms_func: MatchesTargetTerms,
) -> None:
    index, query, search_results, search_error = payload
    if search_error:
        error = {"source": query, "error": search_error}
        errors.append(error)
        query_results[index]["errors"].append(search_error)
        return
    for result in search_results:
        _queue_search_result_fetch(
            index,
            result,
            fetch_tasks=fetch_tasks,
            seen_urls=seen_urls,
            target_terms=target_terms,
            fetcher=fetcher,
            fetch_semaphore=fetch_semaphore,
            news_fetcher_cls=news_fetcher_cls,
            matches_target_terms_func=matches_target_terms_func,
        )


def _queue_search_result_fetch(
    index: int,
    result: dict,
    *,
    fetch_tasks: list[Awaitable[tuple[int, object | None, dict | None]]],
    seen_urls: set[str],
    target_terms: list[str] | None,
    fetcher: Any,
    fetch_semaphore: asyncio.Semaphore,
    news_fetcher_cls: type[NewsFetcher],
    matches_target_terms_func: MatchesTargetTerms,
) -> None:
    url = result.get("url") or ""
    if not url or url in seen_urls:
        return
    seen_urls.add(url)
    preview = _preview_document(news_fetcher_cls, result, url)
    if not matches_target_terms_func(preview, target_terms):
        return
    fetch_tasks.append(
        _fetch_result(
            index,
            result,
            preview,
            fetcher=fetcher,
            fetch_semaphore=fetch_semaphore,
            matches_target_terms_func=matches_target_terms_func,
            target_terms=target_terms,
        )
    )


def _preview_document(news_fetcher_cls: type[NewsFetcher], result: dict, url: str) -> Any:
    return news_fetcher_cls.from_manual_text(
        title=result.get("title") or url,
        text=result.get("snippet") or result.get("title") or url,
        publisher=result.get("publisher") or "web search",
        url=url,
    )


async def _fetch_result(
    index: int,
    result: dict,
    preview: object,
    *,
    fetcher: Any,
    fetch_semaphore: asyncio.Semaphore,
    matches_target_terms_func: MatchesTargetTerms,
    target_terms: list[str] | None,
) -> tuple[int, object | None, dict | None]:
    url = result.get("url") or ""
    async with fetch_semaphore:
        try:
            document = await asyncio.wait_for(
                fetcher.fetch_url(url, publisher=result.get("publisher") or "web search"),
                timeout=FETCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            error = {"source": url, "error": str(exc) or exc.__class__.__name__}
            document = preview
        else:
            error = None
    if not matches_target_terms_func(document, target_terms):
        return index, None, error
    return index, document, error


async def _collect_fetched_documents(
    fetch_tasks: list[Awaitable[tuple[int, object | None, dict | None]]],
    *,
    errors: list[dict],
    query_results: list[dict],
) -> tuple[list[Any], list[dict]]:
    documents = []
    for index, document, error in await asyncio.gather(*fetch_tasks):
        if error:
            errors.append(error)
            query_results[index]["errors"].append(error)
        if document is None:
            continue
        documents.append(document)
        query_results[index]["count"] += 1
    return documents, errors


def _persist_web_search_documents(
    documents: list[Any],
    *,
    mapper: Any,
    vector_store_cls: type,
    session_scope_func: SessionScope,
    news_repository_cls: type,
) -> list[dict]:
    vector_store_cls().upsert_documents(documents)
    ingested = []
    with session_scope_func() as session:
        repository = news_repository_cls(session)
        for document in documents:
            matches = mapper.match_document(document)
            repository.upsert_document(
                document,
                [match.model_dump(mode="json") for match in matches],
            )
            ingested.append(
                {
                    "id": document.id,
                    "title": document.title,
                    "publisher": document.source.publisher,
                    "published_at": document.source.published_at.isoformat()
                    if document.source.published_at
                    else None,
                    "url": document.source.url,
                    "entity_matches": [match.model_dump(mode="json") for match in matches],
                }
            )
    return ingested


def _web_search_result_payload(
    *,
    ingested: list[dict],
    errors: list[dict],
    query_results: list[dict],
    target_terms: list[str] | None,
    topic: str | None,
    selected_count: int,
) -> dict:
    return {
        "count": len(ingested),
        "items": ingested,
        "errors": errors,
        "queries": query_results,
        "target_terms": target_terms or [],
        "source": "DuckDuckGo targeted web search",
        "source_selection": {
            "mode": "targeted_web_search",
            "topic": topic,
            "selected_count": selected_count,
        },
    }


__all__ = ["ingest_web_search_for_pipeline"]
