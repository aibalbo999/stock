from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, timedelta

from app.core.time import today_taipei
from app.data_sources.company_filing_discovery import REQUIRED_CORE_DOCUMENT_TYPES
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.rag.vector_store import VectorStore
from app.services.company_filing_repository import CompanyFilingRepository
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
from app.services.ingestion_documents import (
    dedupe_documents as _dedupe_documents,
    filter_documents as _filter_documents,
    is_low_quality_market_source as _is_low_quality_market_source,
    market_sources as _market_sources,
    matches_target_terms as _matches_target_terms,
    select_diverse_sources as _select_diverse_sources,
    source_category_counts as _source_category_counts,
    source_selection_limit as _source_selection_limit,
    stale_market_source_count as _stale_market_source_count,
)
from app.services.news_repository import NewsRepository
from app.services.ingestion_company_filing_cache import (
    cached_company_filings_by_ticker,
    company_name_from_cached_evidence,
)
from app.services.ingestion_company_filings import fetch_company_filing_ticker_documents
from app.services.ingestion_market import (
    refresh_financial_metric_history,
    refresh_market_snapshots,
    refresh_monthly_revenue_history,
    refresh_valuation_metrics,
)
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

    _source_selection_limit = staticmethod(_source_selection_limit)
    _select_diverse_sources = staticmethod(_select_diverse_sources)
    _source_category_counts = staticmethod(_source_category_counts)
    _matches_target_terms = staticmethod(_matches_target_terms)

    async def refresh_market(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        return await refresh_market_snapshots(
            mapper=self.mapper,
            market_client=self._market_client(),
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            filter_allowed=filter_allowed,
            check_cancelled=self._check_cancelled,
            session_scope_func=session_scope,
            market_repository_cls=MarketRepository,
            market_sources_func=self._market_sources,
            stale_source_count_func=self._stale_market_source_count,
        )

    async def refresh_monthly_revenue(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        return await refresh_monthly_revenue_history(
            mapper=self.mapper,
            market_client=self._market_client(),
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            filter_allowed=filter_allowed,
            check_cancelled=self._check_cancelled,
            session_scope_func=session_scope,
            monthly_revenue_repository_cls=MonthlyRevenueRepository,
            stale_source_count_func=self._stale_market_source_count,
        )

    async def refresh_financial_metrics(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        return await refresh_financial_metric_history(
            mapper=self.mapper,
            market_client=self._market_client(),
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            filter_allowed=filter_allowed,
            check_cancelled=self._check_cancelled,
            session_scope_func=session_scope,
            financial_metric_repository_cls=FinancialMetricRepository,
            stale_source_count_func=self._stale_market_source_count,
        )

    async def refresh_valuations(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        return await refresh_valuation_metrics(
            mapper=self.mapper,
            market_client=self._market_client(),
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            filter_allowed=filter_allowed,
            check_cancelled=self._check_cancelled,
            session_scope_func=session_scope,
            valuation_metric_repository_cls=ValuationMetricRepository,
            stale_source_count_func=self._stale_market_source_count,
        )

    _stale_market_source_count = staticmethod(_stale_market_source_count)
    _market_sources = staticmethod(_market_sources)

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
            ticker_fetch_result = await fetch_company_filing_ticker_documents(
                fetcher=fetcher,
                ticker=ticker,
                company_name=company_name,
                cached_documents=cached_documents,
                target_document_types=target_document_types,
                document_types=document_types,
                limit_per_query=limit_per_query,
                check_cancelled=self._check_cancelled,
            )
            company_documents = ticker_fetch_result["documents"]
            enriched_errors = ticker_fetch_result["errors"]
            attempts = ticker_fetch_result["attempts"]
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

    _company_name_from_cached_evidence = staticmethod(company_name_from_cached_evidence)
    _cached_company_filings_by_ticker = staticmethod(cached_company_filings_by_ticker)

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

    _dedupe_documents = staticmethod(_dedupe_documents)
    _filter_documents = staticmethod(_filter_documents)
    _is_low_quality_market_source = staticmethod(_is_low_quality_market_source)
