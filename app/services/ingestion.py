from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from datetime import date, timedelta

from sqlalchemy import select

from app.core.time import today_taipei
from app.data_sources.company_filing_discovery import (
    REQUIRED_CORE_DOCUMENT_TYPES,
    is_high_quality_company_filing,
)
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.models import NewsArticle
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.rag.vector_store import VectorStore
from app.services.entity_mapping import EntityMapper
from app.services.company_filing_results import (
    COMPANY_FILING_BROWSER_RECOVERY_CATEGORIES,
    COMPANY_FILING_BROWSER_SETUP_CATEGORIES,
    COMPANY_FILING_BROADEN_SEARCH_CATEGORIES,
    COMPANY_FILING_MANUAL_BLOCKING_CATEGORIES,
    COMPANY_FILING_PDF_SETUP_CATEGORIES,
    COMPANY_FILING_TEXT_RECOVERY_CATEGORIES,
    COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES,
    COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES,
    LEGACY_COMPANY_FILING_ERROR_CATEGORY_MAP,
    classify_company_filing_error,
    company_filing_attempt_result,
    company_filing_error_category_counts,
    company_filing_error_is_retryable,
    company_filing_gap_summary,
    company_filing_next_action_type,
    company_filing_next_actions,
    company_filing_next_step,
    company_filing_status,
    company_filing_ticker_result,
    enrich_company_filing_errors,
    missing_company_filing_document_types,
    normalize_company_filing_error_category,
    should_broaden_company_filing_search,
    should_retry_company_filing_fetch,
)
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.persistence import (
    CompanyFilingRepository,
    NewsRepository,
)
from app.services.report_quality import is_stale_market_data_source
from app.services.source_quality import is_low_quality_investor_forum_document
from app.services.task_cancellation import TaskCancelledError

__all__ = [
    "COMPANY_FILING_BROWSER_RECOVERY_CATEGORIES",
    "COMPANY_FILING_BROWSER_SETUP_CATEGORIES",
    "COMPANY_FILING_BROADEN_SEARCH_CATEGORIES",
    "COMPANY_FILING_MANUAL_BLOCKING_CATEGORIES",
    "COMPANY_FILING_PDF_SETUP_CATEGORIES",
    "COMPANY_FILING_TEXT_RECOVERY_CATEGORIES",
    "COMPANY_FILING_VISUAL_RAG_RECOVERY_CATEGORIES",
    "COMPANY_FILING_VISUAL_RAG_SETUP_CATEGORIES",
    "IngestionPipeline",
    "LEGACY_COMPANY_FILING_ERROR_CATEGORY_MAP",
    "classify_company_filing_error",
    "company_filing_attempt_result",
    "company_filing_error_category_counts",
    "company_filing_error_is_retryable",
    "company_filing_gap_summary",
    "company_filing_next_action_type",
    "company_filing_next_actions",
    "company_filing_next_step",
    "company_filing_status",
    "company_filing_ticker_result",
    "enrich_company_filing_errors",
    "missing_company_filing_document_types",
    "normalize_company_filing_error_category",
    "should_broaden_company_filing_search",
    "should_retry_company_filing_fetch",
]


class IngestionPipeline:
    def __init__(self, cancellation_checker: Callable[[], None] | None = None) -> None:
        self.mapper = EntityMapper()
        self.cancellation_checker = cancellation_checker

    def _check_cancelled(self) -> None:
        if self.cancellation_checker is not None:
            self.cancellation_checker()

    def _market_client(self) -> MarketDataClient:
        return MarketDataClient(cancellation_checker=self._check_cancelled)

    async def ingest_feeds(
        self,
        url: str | None = None,
        publisher: str | None = None,
        limit: int = 10,
        enabled_sources_only: bool = True,
        topic: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        quality_filter: bool = True,
    ) -> dict:
        self._check_cancelled()
        fetcher = NewsFetcher()
        documents = []
        errors = []
        fetch_limit = limit * 4 if start_date or end_date or quality_filter else limit
        if url:
            try:
                documents.extend(await fetcher.fetch_feed(url, publisher, fetch_limit))
            except Exception as exc:
                errors.append({"source": url, "error": str(exc)})
            documents = self._filter_documents(documents, start_date, end_date, quality_filter)[
                :limit
            ]
            source_selection = {
                "mode": "single_url",
                "selected_count": 1 if url else 0,
                "available_count": 1 if url else 0,
            }
        else:
            source_store = NewsSourceStore()
            available_sources = source_store.load()
            sources = (
                source_store.sources_for_topic(topic) if enabled_sources_only else available_sources
            )
            source_limit = self._source_selection_limit(limit)
            sources = self._select_diverse_sources(sources, limit=source_limit)
            selection = source_store.selection_for_topic(topic)
            source_selection = {
                "mode": "topic_filtered" if enabled_sources_only else "all_sources",
                "topic": topic,
                "selected_count": len(sources),
                "available_count": len(available_sources),
                "selected_sources": [source.name for source in sources],
                "skipped_sources": [
                    source.name
                    for source in available_sources
                    if source.enabled and source not in sources
                ],
                "selected": selection["selected"] if enabled_sources_only else [],
                "skipped": selection["skipped"] if enabled_sources_only else [],
            }
            source_results = []
            semaphore = asyncio.Semaphore(6)

            async def fetch_source(source):
                async with semaphore:
                    self._check_cancelled()
                    try:
                        source_documents = await asyncio.wait_for(
                            fetcher.fetch_feed(
                                source.url,
                                source.publisher or source.name,
                                fetch_limit,
                            ),
                            timeout=8,
                        )
                        filtered_documents = self._filter_documents(
                            source_documents, start_date, end_date, quality_filter
                        )[:limit]
                        return (
                            filtered_documents,
                            {
                                "name": source.name,
                                "publisher": source.publisher or source.name,
                                "url": source.url,
                                "category": source.category,
                                "scope": source.scope,
                                "topics": source.topics,
                                "source_intents": source.source_intents,
                                "fetch_mode": "rss_or_atom",
                                "stored_count": len(filtered_documents),
                                "error_count": 0,
                            },
                            None,
                        )
                    except TaskCancelledError:
                        raise
                    except Exception as exc:
                        return (
                            [],
                            {
                                "name": source.name,
                                "publisher": source.publisher or source.name,
                                "url": source.url,
                                "category": source.category,
                                "scope": source.scope,
                                "topics": source.topics,
                                "source_intents": source.source_intents,
                                "fetch_mode": "rss_or_atom",
                                "stored_count": 0,
                                "error_count": 1,
                            },
                            {"source": source.url, "error": str(exc) or exc.__class__.__name__},
                        )

            for filtered_documents, source_result, error in await asyncio.gather(
                *(fetch_source(source) for source in sources)
            ):
                self._check_cancelled()
                documents.extend(filtered_documents)
                source_results.append(source_result)
                if error:
                    errors.append(error)
        if url:
            source_results = []

        documents = self._dedupe_documents(documents)
        self._check_cancelled()
        VectorStore().upsert_documents(documents)
        ingested = []
        with session_scope() as session:
            repository = NewsRepository(session)
            for document in documents:
                matches = self.mapper.match_document(document)
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
                        "entity_matches": [match.model_dump(mode="json") for match in matches],
                    }
                )
        return {
            "count": len(ingested),
            "items": ingested,
            "errors": errors,
            "source_results": source_results,
            "source_category_counts": self._source_category_counts(source_results),
            "source_selection": source_selection,
        }

    async def ingest_web_search(
        self,
        queries: list[str],
        topic: str | None = None,
        limit_per_query: int = 5,
        start_date: date | None = None,
        end_date: date | None = None,
        target_terms: list[str] | None = None,
        quality_filter: bool = True,
    ) -> dict:
        fetcher = NewsFetcher()
        documents = []
        errors = []
        query_results = [{"query": query, "count": 0, "errors": []} for query in queries]
        seen_urls: set[str] = set()
        search_timeout = 10
        fetch_timeout = 8
        fetch_semaphore = asyncio.Semaphore(12)

        async def search_query(index: int, query: str) -> tuple[int, str, list[dict], str | None]:
            try:
                search_results = await asyncio.wait_for(
                    CompanyFilingFetcher._duckduckgo_search(query, limit_per_query),
                    timeout=search_timeout,
                )
            except Exception as exc:
                return index, query, [], str(exc) or exc.__class__.__name__
            return index, query, search_results, None

        async def fetch_result(
            index: int, result: dict, preview: object
        ) -> tuple[int, object | None, dict | None]:
            url = result.get("url") or ""
            async with fetch_semaphore:
                try:
                    document = await asyncio.wait_for(
                        fetcher.fetch_url(url, publisher=result.get("publisher") or "web search"),
                        timeout=fetch_timeout,
                    )
                except Exception as exc:
                    error = {"source": url, "error": str(exc) or exc.__class__.__name__}
                    document = preview
                else:
                    error = None
            if not self._matches_target_terms(document, target_terms):
                return index, None, error
            return index, document, error

        search_payloads = await asyncio.gather(
            *(search_query(index, query) for index, query in enumerate(queries))
        )
        fetch_tasks = []
        for index, query, search_results, search_error in search_payloads:
            if search_error:
                error = {"source": query, "error": search_error}
                errors.append(error)
                query_results[index]["errors"].append(search_error)
                continue
            for result in search_results:
                url = result.get("url") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                preview = NewsFetcher.from_manual_text(
                    title=result.get("title") or url,
                    text=result.get("snippet") or result.get("title") or url,
                    publisher=result.get("publisher") or "web search",
                    url=url,
                )
                if not self._matches_target_terms(preview, target_terms):
                    continue
                fetch_tasks.append(fetch_result(index, result, preview))

        for index, document, error in await asyncio.gather(*fetch_tasks):
            if error:
                errors.append(error)
                query_results[index]["errors"].append(error)
            if document is None:
                continue
            documents.append(document)
            query_results[index]["count"] += 1

        documents = self._filter_documents(
            self._dedupe_documents(documents),
            start_date,
            end_date,
            quality_filter,
        )
        VectorStore().upsert_documents(documents)
        ingested = []
        with session_scope() as session:
            repository = NewsRepository(session)
            for document in documents:
                matches = self.mapper.match_document(document)
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
                "selected_count": len(queries),
            },
        }

    @staticmethod
    def _source_selection_limit(limit: int) -> int:
        return max(20, min(40, limit + 16))

    @staticmethod
    def _select_diverse_sources(sources: list, limit: int) -> list:
        if len(sources) <= limit:
            return sources
        selected: list = []
        used_names: set[str] = set()
        seen_categories: set[str] = set()
        for source in sources:
            if source.category in seen_categories:
                continue
            selected.append(source)
            used_names.add(source.name)
            seen_categories.add(source.category)
            if len(selected) >= limit:
                return selected
        for source in sources:
            if source.name in used_names:
                continue
            selected.append(source)
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def _source_category_counts(source_results: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for result in source_results:
            category = str(result.get("category") or "news")
            counts[category] = counts.get(category, 0) + int(result.get("stored_count") or 0)
        return counts

    @staticmethod
    def _matches_target_terms(document, target_terms: list[str] | None) -> bool:
        terms = [
            term.casefold() for term in (target_terms or []) if term and len(term.strip()) >= 2
        ]
        if not terms:
            return True
        haystack = " ".join(
            str(part or "")
            for part in [
                getattr(document, "title", ""),
                getattr(document, "text", ""),
                getattr(getattr(document, "source", None), "url", ""),
                getattr(getattr(document, "source", None), "publisher", ""),
            ]
        ).casefold()
        return any(term in haystack for term in terms)

    async def refresh_market(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        requested = tickers or sorted(self.mapper.whitelist.allowed_tickers())
        allowed = self.mapper.filter_allowed_tickers(requested) if filter_allowed else requested
        self._check_cancelled()
        histories, errors = await self._market_client().get_price_histories_with_errors(
            allowed,
            start_date,
            end_date,
            force_refresh=True,
        )
        self._check_cancelled()
        all_snapshots = [snapshot for history in histories.values() for snapshot in history]
        latest_snapshots = [
            sorted(history, key=lambda snapshot: snapshot.trade_date)[-1]
            for history in histories.values()
            if history
        ]
        sources = self._market_sources(all_snapshots)
        with session_scope() as session:
            MarketRepository(session).upsert_snapshots(all_snapshots)
        return {
            "requested_tickers": allowed,
            "stored": [snapshot.model_dump(mode="json") for snapshot in latest_snapshots],
            "stored_history_count": len(all_snapshots),
            "stale_source_count": self._stale_market_source_count(all_snapshots),
            "errors": [error.model_dump() for error in errors],
            "source": ", ".join(sources) if sources else "market data providers",
            "sources": sources,
        }

    async def refresh_monthly_revenue(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        requested = tickers or sorted(self.mapper.whitelist.allowed_tickers())
        allowed = self.mapper.filter_allowed_tickers(requested) if filter_allowed else requested
        self._check_cancelled()
        revenues, errors = await self._market_client().get_monthly_revenue_histories_with_errors(
            allowed,
            start_date,
            end_date,
        )
        self._check_cancelled()
        with session_scope() as session:
            repository = MonthlyRevenueRepository(session)
            repository.upsert_revenues(revenues)
            latest = repository.latest_by_tickers(allowed)
        return {
            "requested_tickers": allowed,
            "stored_count": len(revenues),
            "latest": [revenue.model_dump(mode="json") for revenue in latest],
            "stale_source_count": self._stale_market_source_count(revenues),
            "errors": [error.model_dump() for error in errors],
            "source": "FinMind TaiwanStockMonthRevenue",
        }

    async def refresh_financial_metrics(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        requested = tickers or sorted(self.mapper.whitelist.allowed_tickers())
        allowed = self.mapper.filter_allowed_tickers(requested) if filter_allowed else requested
        self._check_cancelled()
        metrics, errors = await self._market_client().get_financial_metrics_histories_with_errors(
            allowed,
            start_date,
            end_date,
        )
        self._check_cancelled()
        with session_scope() as session:
            FinancialMetricRepository(session).upsert_metrics(metrics)
        return {
            "requested_tickers": allowed,
            "stored_count": len(metrics),
            "stale_source_count": self._stale_market_source_count(metrics),
            "errors": [error.model_dump() for error in errors],
            "source": "FinMind financial statements",
        }

    async def refresh_valuations(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        requested = tickers or sorted(self.mapper.whitelist.allowed_tickers())
        allowed = self.mapper.filter_allowed_tickers(requested) if filter_allowed else requested
        self._check_cancelled()
        valuations, errors = await self._market_client().get_latest_valuations_with_errors(
            allowed,
            start_date,
            end_date,
        )
        self._check_cancelled()
        with session_scope() as session:
            ValuationMetricRepository(session).upsert_valuations(valuations)
        return {
            "requested_tickers": allowed,
            "stored": [valuation.model_dump(mode="json") for valuation in valuations],
            "stale_source_count": self._stale_market_source_count(valuations),
            "errors": [error.model_dump() for error in errors],
            "source": "FinMind TaiwanStockPER",
        }

    @staticmethod
    def _stale_market_source_count(rows: list[object]) -> int:
        return sum(1 for row in rows if is_stale_market_data_source(getattr(row, "source", "")))

    @staticmethod
    def _market_sources(rows: list[object]) -> list[str]:
        sources: list[str] = []
        for row in rows:
            source = str(getattr(row, "source", "") or "").strip()
            if source and source not in sources:
                sources.append(source)
        return sources

    async def ingest_company_filings(
        self,
        tickers: list[str],
        limit_per_query: int = 3,
        filter_allowed: bool = True,
        document_types: list[str] | None = None,
        company_names: dict[str, str] | None = None,
    ) -> dict:
        requested = tickers or sorted(self.mapper.whitelist.allowed_tickers())
        allowed = self.mapper.filter_allowed_tickers(requested) if filter_allowed else requested
        companies = {company.ticker: company for company in self.mapper.whitelist.companies()}
        fetcher = CompanyFilingFetcher()
        documents = []
        errors = []
        search_plans = []
        per_ticker_results = []
        target_document_types = tuple(document_types or REQUIRED_CORE_DOCUMENT_TYPES)
        company_names = company_names or {}
        cached_documents_by_ticker = self._cached_company_filings_by_ticker(allowed)
        for ticker in allowed:
            self._check_cancelled()
            company = companies.get(ticker)
            cached_documents = cached_documents_by_ticker.get(ticker, [])
            company_name = (
                company_names.get(ticker)
                or (company.name if company else "")
                or next(
                    (
                        document.company_name or ""
                        for document in cached_documents
                        if document.company_name
                    ),
                    "",
                )
                or self._company_name_from_cached_evidence(ticker)
            )
            search_plans.append(
                fetcher.official_search_plan(ticker, company_name, document_types=document_types)
            )
            attempts = []
            company_documents = list(cached_documents)
            enriched_errors = []
            latest_errors = []
            if cached_documents:
                attempts.append(
                    company_filing_attempt_result(
                        "cached_company_filings",
                        cached_documents,
                        [],
                    )
                )
            mops_attempted = False
            missing_document_types = missing_company_filing_document_types(
                company_documents,
                list(target_document_types),
            )
            if "annual_report" in missing_document_types:
                mops_documents, mops_errors = await fetcher.fetch_mops_annual_report_documents(
                    ticker,
                    company_name,
                )
                self._check_cancelled()
                mops_attempted = True
                mops_enriched_errors = enrich_company_filing_errors(
                    mops_errors, ticker, company_name
                )
                company_documents.extend(mops_documents)
                enriched_errors.extend(mops_enriched_errors)
                latest_errors = mops_enriched_errors
                attempts.append(
                    company_filing_attempt_result(
                        "mops_annual_report",
                        mops_documents,
                        mops_enriched_errors,
                    )
                )
            missing_document_types = missing_company_filing_document_types(
                company_documents,
                list(target_document_types),
            )
            if should_broaden_company_filing_search(
                company_documents, enriched_errors, list(target_document_types)
            ):
                fetched_documents, company_errors = await fetcher.fetch_discovery_documents(
                    ticker,
                    company_name,
                    limit_per_query=limit_per_query,
                    document_types=missing_document_types or document_types,
                )
                self._check_cancelled()
                targeted_enriched_errors = enrich_company_filing_errors(
                    company_errors, ticker, company_name
                )
                company_documents.extend(fetched_documents)
                enriched_errors.extend(targeted_enriched_errors)
                latest_errors = targeted_enriched_errors
                attempts.append(
                    company_filing_attempt_result(
                        "targeted_search",
                        fetched_documents,
                        targeted_enriched_errors,
                    )
                )
            if should_retry_company_filing_fetch(company_documents, latest_errors):
                missing_document_types = missing_company_filing_document_types(
                    company_documents,
                    list(target_document_types),
                )
                retry_documents, retry_errors = await fetcher.fetch_discovery_documents(
                    ticker,
                    company_name,
                    limit_per_query=limit_per_query,
                    document_types=missing_document_types or document_types,
                )
                self._check_cancelled()
                retry_enriched_errors = enrich_company_filing_errors(
                    retry_errors, ticker, company_name
                )
                company_documents.extend(retry_documents)
                enriched_errors.extend(retry_enriched_errors)
                latest_errors = retry_enriched_errors
                attempts.append(
                    company_filing_attempt_result(
                        "retry_after_source_error",
                        retry_documents,
                        retry_enriched_errors,
                    )
                )
            if should_broaden_company_filing_search(
                company_documents, enriched_errors, list(target_document_types)
            ):
                broad_documents, broad_errors = await fetcher.fetch_discovery_documents(
                    ticker,
                    company_name,
                    limit_per_query=limit_per_query + 2,
                    document_types=None,
                )
                self._check_cancelled()
                broad_enriched_errors = enrich_company_filing_errors(
                    broad_errors, ticker, company_name
                )
                company_documents.extend(broad_documents)
                enriched_errors.extend(broad_enriched_errors)
                latest_errors = broad_enriched_errors
                attempts.append(
                    company_filing_attempt_result(
                        "broaden_official_search",
                        broad_documents,
                        broad_enriched_errors,
                    )
                )
            missing_document_types = missing_company_filing_document_types(
                company_documents,
                list(target_document_types),
            )
            if not mops_attempted and "annual_report" in missing_document_types:
                mops_documents, mops_errors = await fetcher.fetch_mops_annual_report_documents(
                    ticker,
                    company_name,
                )
                self._check_cancelled()
                mops_enriched_errors = enrich_company_filing_errors(
                    mops_errors, ticker, company_name
                )
                company_documents.extend(mops_documents)
                enriched_errors.extend(mops_enriched_errors)
                latest_errors = mops_enriched_errors
                attempts.append(
                    company_filing_attempt_result(
                        "mops_annual_report",
                        mops_documents,
                        mops_enriched_errors,
                    )
                )
            missing_document_types = missing_company_filing_document_types(
                company_documents,
                list(target_document_types),
            )
            if should_broaden_company_filing_search(
                company_documents, enriched_errors, list(target_document_types)
            ):
                (
                    official_documents,
                    official_errors,
                ) = await fetcher.fetch_official_website_documents(
                    ticker,
                    company_name,
                    limit=limit_per_query + 5,
                    document_types=missing_document_types or document_types,
                )
                self._check_cancelled()
                official_enriched_errors = enrich_company_filing_errors(
                    official_errors, ticker, company_name
                )
                company_documents.extend(official_documents)
                enriched_errors.extend(official_enriched_errors)
                latest_errors = official_enriched_errors
                attempts.append(
                    company_filing_attempt_result(
                        "official_company_website",
                        official_documents,
                        official_enriched_errors,
                    )
                )
            missing_document_types = missing_company_filing_document_types(
                company_documents,
                list(target_document_types),
            )
            if should_broaden_company_filing_search(
                company_documents, enriched_errors, list(target_document_types)
            ):
                web_documents, web_errors = await fetcher.fetch_web_search_documents(
                    ticker,
                    company_name,
                    limit_per_query=limit_per_query + 3,
                    document_types=missing_document_types or document_types,
                )
                self._check_cancelled()
                web_enriched_errors = enrich_company_filing_errors(web_errors, ticker, company_name)
                company_documents.extend(web_documents)
                enriched_errors.extend(web_enriched_errors)
                latest_errors = web_enriched_errors
                attempts.append(
                    company_filing_attempt_result(
                        "official_web_search",
                        web_documents,
                        web_enriched_errors,
                    )
                )
            company_documents = self._dedupe_documents(company_documents)
            documents.extend(company_documents)
            errors.extend(enriched_errors)
            per_ticker_results.append(
                company_filing_ticker_result(
                    ticker,
                    company_name,
                    company_documents,
                    target_document_types,
                    enriched_errors,
                    attempts,
                )
            )

        news_documents = [
            CompanyFilingRepository.to_news_document(document) for document in documents
        ]
        self._check_cancelled()
        VectorStore().upsert_documents(news_documents)
        with session_scope() as session:
            repository = CompanyFilingRepository(session)
            for document in documents:
                repository.upsert_document(document)
        return {
            "requested_tickers": allowed,
            "stored_count": len(documents),
            "items": [
                {
                    "id": document.id,
                    "ticker": document.ticker,
                    "document_type": document.document_type,
                    "title": document.title,
                    "publisher": document.source.publisher,
                    "published_at": document.source.published_at.isoformat()
                    if document.source.published_at
                    else None,
                    "url": document.source.url,
                }
                for document in documents
            ],
            "errors": errors,
            "per_ticker_results": per_ticker_results,
            "missing_tickers": [
                row["ticker"] for row in per_ticker_results if row["status"] != "sufficient"
            ],
            "gap_summary": company_filing_gap_summary(per_ticker_results),
            "next_actions": company_filing_next_actions(per_ticker_results),
            "official_search_plans": search_plans,
            "source": "Company filing discovery (Google News + official web search)",
        }

    async def ingest_mops_annual_reports(
        self,
        tickers: list[str],
        filter_allowed: bool = True,
    ) -> dict:
        requested = tickers or []
        allowed = self.mapper.filter_allowed_tickers(requested) if filter_allowed else requested
        companies = {company.ticker: company for company in self.mapper.whitelist.companies()}
        fetcher = CompanyFilingFetcher()
        documents = []
        errors = []
        per_ticker_results = []
        for ticker in allowed:
            self._check_cancelled()
            company = companies.get(ticker)
            company_name = (
                company.name if company else self._company_name_from_cached_evidence(ticker)
            )
            try:
                ticker_documents, ticker_errors = await asyncio.wait_for(
                    fetcher.fetch_mops_annual_report_documents(ticker, company_name),
                    timeout=30,
                )
            except TaskCancelledError:
                raise
            except Exception as exc:
                ticker_documents = []
                ticker_errors = [
                    {"source": "MOPS annual report", "error": str(exc) or exc.__class__.__name__}
                ]
            enriched_errors = enrich_company_filing_errors(ticker_errors, ticker, company_name)
            documents.extend(ticker_documents)
            errors.extend(enriched_errors)
            per_ticker_results.append(
                company_filing_ticker_result(
                    ticker,
                    company_name,
                    ticker_documents,
                    ("annual_report",),
                    enriched_errors,
                    [
                        company_filing_attempt_result(
                            "mops_annual_report", ticker_documents, enriched_errors
                        )
                    ],
                )
            )

        documents = self._dedupe_documents(documents)
        self._check_cancelled()
        news_documents = [
            CompanyFilingRepository.to_news_document(document) for document in documents
        ]
        VectorStore().upsert_documents(news_documents)
        with session_scope() as session:
            repository = CompanyFilingRepository(session)
            for document in documents:
                repository.upsert_document(document)
        return {
            "requested_tickers": allowed,
            "stored_count": len(documents),
            "items": [
                {
                    "id": document.id,
                    "ticker": document.ticker,
                    "document_type": document.document_type,
                    "title": document.title,
                    "publisher": document.source.publisher,
                    "published_at": document.source.published_at.isoformat()
                    if document.source.published_at
                    else None,
                    "url": document.source.url,
                }
                for document in documents
            ],
            "errors": errors,
            "per_ticker_results": per_ticker_results,
            "missing_tickers": [
                row["ticker"] for row in per_ticker_results if row["status"] != "sufficient"
            ],
            "gap_summary": company_filing_gap_summary(per_ticker_results),
            "next_actions": company_filing_next_actions(per_ticker_results),
            "source": "MOPS annual report direct discovery",
        }

    @staticmethod
    def _company_name_from_cached_evidence(ticker: str) -> str:
        try:
            with session_scope() as session:
                rows = session.scalars(
                    select(NewsArticle.entity_matches_json)
                    .where(NewsArticle.entity_matches_json.like(f"%{ticker}%"))
                    .limit(50)
                )
                names = []
                for raw in rows:
                    for match in json.loads(raw or "[]"):
                        if str(match.get("ticker") or "") == ticker and match.get("name"):
                            names.append(str(match["name"]))
                if names:
                    return max(set(names), key=names.count)
        except Exception:
            return ""
        return ""

    @staticmethod
    def _cached_company_filings_by_ticker(
        tickers: list[str],
        limit_per_ticker: int = 8,
    ) -> dict[str, list]:
        if not tickers:
            return {}
        cached: dict[str, list] = {ticker: [] for ticker in tickers}
        try:
            with session_scope() as session:
                repository = CompanyFilingRepository(session)
                latest_by_tickers = getattr(repository, "latest_by_tickers", None)
                if latest_by_tickers is None:
                    return cached
                documents = latest_by_tickers(tickers, limit_per_ticker=limit_per_ticker)
        except Exception:
            return cached
        for document in documents:
            ticker = str(getattr(document, "ticker", "") or "")
            if ticker not in cached:
                continue
            company_name = str(getattr(document, "company_name", "") or "")
            if is_high_quality_company_filing(document, ticker, company_name):
                cached[ticker].append(document)
        return cached

    async def pre_report_refresh(self, request: ReportRequest) -> dict:
        self._check_cancelled()
        end_date = today_taipei()
        start_date = end_date - timedelta(days=request.lookback_days)
        tickers = self.mapper.filter_allowed_tickers(request.tickers)
        if not tickers:
            tickers = sorted(self.mapper.whitelist.allowed_tickers())
        news = await self.ingest_feeds(
            enabled_sources_only=True,
            topic=request.topic,
            limit=max(10, min(30, request.evidence_limit // 4)),
            start_date=start_date,
            end_date=end_date,
        )
        self._check_cancelled()
        market = await self.refresh_market(tickers, start_date, end_date)
        self._check_cancelled()
        monthly_revenue = await self.refresh_monthly_revenue(
            tickers,
            end_date - timedelta(days=450),
            end_date,
        )
        self._check_cancelled()
        financial_metrics = await self.refresh_financial_metrics(
            tickers,
            end_date - timedelta(days=365 * 6),
            end_date,
        )
        self._check_cancelled()
        valuations = await self.refresh_valuations(
            tickers,
            start_date,
            end_date,
        )
        self._check_cancelled()
        company_filings = await self.ingest_company_filings(
            tickers,
            limit_per_query=2,
            filter_allowed=False,
        )
        return {
            "news": news,
            "market": market,
            "monthly_revenue": monthly_revenue,
            "financial_metrics": financial_metrics,
            "valuations": valuations,
            "company_filings": company_filings,
        }

    @staticmethod
    def _dedupe_documents(documents):
        deduped = {}
        for document in documents:
            deduped.setdefault(document.id, document)
        return list(deduped.values())

    @staticmethod
    def _filter_documents(
        documents,
        start_date: date | None,
        end_date: date | None,
        quality_filter: bool,
    ):
        filtered = []
        for document in documents:
            published_at = document.source.published_at
            if published_at and start_date and published_at < start_date:
                continue
            if published_at and end_date and published_at > end_date:
                continue
            if quality_filter and is_low_quality_investor_forum_document(document):
                continue
            if quality_filter and IngestionPipeline._is_low_quality_market_source(document):
                continue
            filtered.append(document)
        return filtered

    @staticmethod
    def _is_low_quality_market_source(document) -> bool:
        text = f"{document.title}\n{document.text}"
        political_noise = [
            "選舉",
            "立委",
            "政黨",
            "民進黨",
            "國民黨",
            "藍白",
            "嗆",
            "打臉",
            "公投",
            "市長",
        ]
        market_terms = [
            "營收",
            "獲利",
            "EPS",
            "訂單",
            "出貨",
            "產能",
            "法說",
            "目標價",
            "股",
            "台廠",
            "CoWoS",
            "HBM",
            "伺服器",
            "散熱",
            "重電",
        ]
        has_political_noise = any(term in text for term in political_noise)
        has_market_context = any(term in text for term in market_terms)
        return has_political_noise and not has_market_context
