from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

from sqlalchemy import select

from app.core.time import today_taipei
from app.data_sources.company_filings import (
    RECOMMENDED_DOCUMENT_TYPES,
    REQUIRED_CORE_DOCUMENT_TYPES,
    CompanyFilingFetcher,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.models import NewsArticle
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.rag.vector_store import VectorStore
from app.services.entity_mapping import EntityMapper
from app.services.persistence import (
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    NewsRepository,
    ValuationMetricRepository,
)


class IngestionPipeline:
    def __init__(self) -> None:
        self.mapper = EntityMapper()

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
        fetcher = NewsFetcher()
        documents = []
        errors = []
        fetch_limit = limit * 4 if start_date or end_date or quality_filter else limit
        if url:
            try:
                documents.extend(await fetcher.fetch_feed(url, publisher, fetch_limit))
            except Exception as exc:
                errors.append({"source": url, "error": str(exc)})
            documents = self._filter_documents(documents, start_date, end_date, quality_filter)[:limit]
            source_selection = {"mode": "single_url", "selected_count": 1 if url else 0, "available_count": 1 if url else 0}
        else:
            source_store = NewsSourceStore()
            available_sources = source_store.load()
            sources = (
                source_store.sources_for_topic(topic)
                if enabled_sources_only
                else available_sources
            )
            source_selection = {
                "mode": "topic_filtered" if enabled_sources_only else "all_sources",
                "topic": topic,
                "selected_count": len(sources),
                "available_count": len(available_sources),
                "selected_sources": [source.name for source in sources],
                "skipped_sources": [source.name for source in available_sources if source.enabled and source not in sources],
            }
            source_results = []
            for source in sources:
                try:
                    source_documents = await fetcher.fetch_feed(
                        source.url,
                        source.publisher or source.name,
                        fetch_limit,
                    )
                    filtered_documents = self._filter_documents(source_documents, start_date, end_date, quality_filter)[:limit]
                    documents.extend(filtered_documents)
                    source_results.append(
                        {
                            "name": source.name,
                            "publisher": source.publisher or source.name,
                            "category": source.category,
                            "scope": source.scope,
                            "topics": source.topics,
                            "source_intents": source.source_intents,
                            "stored_count": len(filtered_documents),
                            "error_count": 0,
                        }
                    )
                except Exception as exc:
                    errors.append({"source": source.url, "error": str(exc)})
                    source_results.append(
                        {
                            "name": source.name,
                            "publisher": source.publisher or source.name,
                            "category": source.category,
                            "scope": source.scope,
                            "topics": source.topics,
                            "source_intents": source.source_intents,
                            "stored_count": 0,
                            "error_count": 1,
                        }
                    )
        if url:
            source_results = []

        documents = self._dedupe_documents(documents)
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

    @staticmethod
    def _source_category_counts(source_results: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for result in source_results:
            category = str(result.get("category") or "news")
            counts[category] = counts.get(category, 0) + int(result.get("stored_count") or 0)
        return counts

    async def refresh_market(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        requested = tickers or sorted(self.mapper.whitelist.allowed_tickers())
        allowed = self.mapper.filter_allowed_tickers(requested) if filter_allowed else requested
        histories, errors = await MarketDataClient().get_price_histories_with_errors(
            allowed,
            start_date,
            end_date,
        )
        all_snapshots = [snapshot for history in histories.values() for snapshot in history]
        latest_snapshots = [
            sorted(history, key=lambda snapshot: snapshot.trade_date)[-1]
            for history in histories.values()
            if history
        ]
        with session_scope() as session:
            MarketRepository(session).upsert_snapshots(all_snapshots)
        return {
            "requested_tickers": allowed,
            "stored": [snapshot.model_dump(mode="json") for snapshot in latest_snapshots],
            "stored_history_count": len(all_snapshots),
            "errors": [error.model_dump() for error in errors],
            "source": "FinMind TaiwanStockPrice",
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
        revenues, errors = await MarketDataClient().get_monthly_revenue_histories_with_errors(
            allowed,
            start_date,
            end_date,
        )
        with session_scope() as session:
            repository = MonthlyRevenueRepository(session)
            repository.upsert_revenues(revenues)
            latest = repository.latest_by_tickers(allowed)
        return {
            "requested_tickers": allowed,
            "stored_count": len(revenues),
            "latest": [revenue.model_dump(mode="json") for revenue in latest],
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
        metrics, errors = await MarketDataClient().get_financial_metrics_histories_with_errors(
            allowed,
            start_date,
            end_date,
        )
        with session_scope() as session:
            FinancialMetricRepository(session).upsert_metrics(metrics)
        return {
            "requested_tickers": allowed,
            "stored_count": len(metrics),
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
        valuations, errors = await MarketDataClient().get_latest_valuations_with_errors(
            allowed,
            start_date,
            end_date,
        )
        with session_scope() as session:
            ValuationMetricRepository(session).upsert_valuations(valuations)
        return {
            "requested_tickers": allowed,
            "stored": [valuation.model_dump(mode="json") for valuation in valuations],
            "errors": [error.model_dump() for error in errors],
            "source": "FinMind TaiwanStockPER",
        }

    async def ingest_company_filings(
        self,
        tickers: list[str],
        limit_per_query: int = 3,
        filter_allowed: bool = True,
        document_types: list[str] | None = None,
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
        for ticker in allowed:
            company = companies.get(ticker)
            company_name = company.name if company else self._company_name_from_cached_evidence(ticker)
            search_plans.append(fetcher.official_search_plan(ticker, company_name, document_types=document_types))
            attempts = []
            company_documents, company_errors = await fetcher.fetch_discovery_documents(
                ticker,
                company_name,
                limit_per_query=limit_per_query,
                document_types=document_types,
            )
            enriched_errors = enrich_company_filing_errors(company_errors, ticker, company_name)
            attempts.append(
                company_filing_attempt_result(
                    "targeted_search",
                    company_documents,
                    enriched_errors,
                )
            )
            if should_retry_company_filing_fetch(company_documents, enriched_errors):
                retry_documents, retry_errors = await fetcher.fetch_discovery_documents(
                    ticker,
                    company_name,
                    limit_per_query=limit_per_query,
                    document_types=document_types,
                )
                retry_enriched_errors = enrich_company_filing_errors(retry_errors, ticker, company_name)
                company_documents.extend(retry_documents)
                enriched_errors.extend(retry_enriched_errors)
                attempts.append(
                    company_filing_attempt_result(
                        "retry_after_source_error",
                        retry_documents,
                        retry_enriched_errors,
                    )
                )
            if should_broaden_company_filing_search(company_documents, enriched_errors, list(target_document_types)):
                broad_documents, broad_errors = await fetcher.fetch_discovery_documents(
                    ticker,
                    company_name,
                    limit_per_query=limit_per_query + 2,
                    document_types=None,
                )
                broad_enriched_errors = enrich_company_filing_errors(broad_errors, ticker, company_name)
                company_documents.extend(broad_documents)
                enriched_errors.extend(broad_enriched_errors)
                attempts.append(
                    company_filing_attempt_result(
                        "broaden_official_search",
                        broad_documents,
                        broad_enriched_errors,
                    )
                )
            if should_broaden_company_filing_search(company_documents, enriched_errors, list(target_document_types)):
                mops_documents, mops_errors = await fetcher.fetch_mops_annual_report_documents(
                    ticker,
                    company_name,
                )
                mops_enriched_errors = enrich_company_filing_errors(mops_errors, ticker, company_name)
                company_documents.extend(mops_documents)
                enriched_errors.extend(mops_enriched_errors)
                attempts.append(
                    company_filing_attempt_result(
                        "mops_annual_report",
                        mops_documents,
                        mops_enriched_errors,
                    )
                )
            if should_broaden_company_filing_search(company_documents, enriched_errors, list(target_document_types)):
                official_documents, official_errors = await fetcher.fetch_official_website_documents(
                    ticker,
                    company_name,
                    limit=limit_per_query + 5,
                    document_types=document_types,
                )
                official_enriched_errors = enrich_company_filing_errors(official_errors, ticker, company_name)
                company_documents.extend(official_documents)
                enriched_errors.extend(official_enriched_errors)
                attempts.append(
                    company_filing_attempt_result(
                        "official_company_website",
                        official_documents,
                        official_enriched_errors,
                    )
                )
            if should_broaden_company_filing_search(company_documents, enriched_errors, list(target_document_types)):
                web_documents, web_errors = await fetcher.fetch_web_search_documents(
                    ticker,
                    company_name,
                    limit_per_query=limit_per_query + 3,
                    document_types=document_types,
                )
                web_enriched_errors = enrich_company_filing_errors(web_errors, ticker, company_name)
                company_documents.extend(web_documents)
                enriched_errors.extend(web_enriched_errors)
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

        news_documents = [CompanyFilingRepository.to_news_document(document) for document in documents]
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
                row["ticker"]
                for row in per_ticker_results
                if row["status"] != "sufficient"
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
            company = companies.get(ticker)
            company_name = company.name if company else self._company_name_from_cached_evidence(ticker)
            try:
                ticker_documents, ticker_errors = await asyncio.wait_for(
                    fetcher.fetch_mops_annual_report_documents(ticker, company_name),
                    timeout=30,
                )
            except Exception as exc:
                ticker_documents = []
                ticker_errors = [{"source": "MOPS annual report", "error": str(exc) or exc.__class__.__name__}]
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
                    [company_filing_attempt_result("mops_annual_report", ticker_documents, enriched_errors)],
                )
            )

        documents = self._dedupe_documents(documents)
        news_documents = [CompanyFilingRepository.to_news_document(document) for document in documents]
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
                row["ticker"]
                for row in per_ticker_results
                if row["status"] != "sufficient"
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

    async def pre_report_refresh(self, request: ReportRequest) -> dict:
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
        market = await self.refresh_market(tickers, start_date, end_date)
        monthly_revenue = await self.refresh_monthly_revenue(
            tickers,
            end_date - timedelta(days=450),
            end_date,
        )
        financial_metrics = await self.refresh_financial_metrics(
            tickers,
            end_date - timedelta(days=365 * 6),
            end_date,
        )
        valuations = await self.refresh_valuations(
            tickers,
            start_date,
            end_date,
        )
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


def classify_company_filing_error(message: str) -> str:
    lowered = message.lower()
    if "ocr" in lowered or "extractable text" in lowered or "掃描" in message:
        return "manual_text_required"
    if any(term in lowered for term in ("429", "rate limit", "too many requests", "503", "500", "timeout")):
        return "retryable_source_error"
    if any(term in lowered for term in ("403", "forbidden", "login", "登入", "captcha")):
        return "source_access_restricted"
    if any(term in lowered for term in ("too short", "does not mention", "does not match")):
        return "content_not_usable"
    return "source_fetch_error"


def enrich_company_filing_errors(errors: list[dict], ticker: str, company_name: str) -> list[dict]:
    return [
        {
            **error,
            "ticker": ticker,
            "company_name": company_name,
            "category": classify_company_filing_error(error.get("error", "")),
        }
        for error in errors
    ]


def should_retry_company_filing_fetch(documents: list, errors: list[dict]) -> bool:
    if documents or not errors:
        return False
    return {error.get("category") for error in errors}.issubset({"retryable_source_error"})


def should_broaden_company_filing_search(
    documents: list,
    errors: list[dict],
    document_types: list[str] | None,
) -> bool:
    if not document_types:
        return False
    available_types = {getattr(document, "document_type", "") for document in documents}
    return any(document_type not in available_types for document_type in document_types)


def company_filing_attempt_result(strategy: str, documents: list, errors: list[dict]) -> dict:
    return {
        "strategy": strategy,
        "stored_count": len(documents),
        "error_count": len(errors),
        "error_categories": sorted({error.get("category", "source_fetch_error") for error in errors}),
    }


def company_filing_ticker_result(
    ticker: str,
    company_name: str,
    documents: list,
    target_document_types: tuple[str, ...],
    errors: list[dict],
    attempts: list[dict] | None = None,
) -> dict:
    document_types = sorted({document.document_type for document in documents})
    missing_required = [
        document_type
        for document_type in target_document_types
        if document_type not in document_types
    ]
    missing_recommended = [
        document_type
        for document_type in RECOMMENDED_DOCUMENT_TYPES
        if document_type not in document_types and document_type not in target_document_types
    ]
    error_categories = sorted({error.get("category", "source_fetch_error") for error in errors})
    status = company_filing_status(documents, missing_required, error_categories)
    return {
        "ticker": ticker,
        "company_name": company_name,
        "stored_count": len(documents),
        "document_types": document_types,
        "missing_required_types": missing_required,
        "missing_recommended_types": missing_recommended,
        "error_count": len(errors),
        "error_categories": error_categories,
        "attempts": attempts or [],
        "status": status,
        "next_step": company_filing_next_step(status, missing_required, missing_recommended),
    }


def company_filing_status(
    documents: list,
    missing_required: list[str],
    error_categories: list[str],
) -> str:
    if documents and not missing_required:
        return "sufficient"
    if error_categories and set(error_categories).issubset({"retryable_source_error"}):
        return "retry_recommended"
    if not documents and not error_categories:
        return "broader_search_recommended"
    return "needs_manual_source"


def company_filing_next_step(
    status: str,
    missing_required: list[str],
    missing_recommended: list[str],
) -> str:
    if status == "sufficient" and not missing_recommended:
        return "公司公開文件已足夠進入個股分析。"
    if status == "retry_recommended":
        return "資料源暫時不穩，系統可稍後自動重試同一批官方搜尋。"
    if status == "broader_search_recommended":
        return "目前搜尋不到足夠文件，系統應擴大官方入口與公司 IR 查詢後再重跑。"
    missing = missing_required or missing_recommended
    if missing:
        return "請補官方文件：" + "、".join(missing) + "；可使用 MOPS、TWSE/TPEx 或公司 IR 的 HTML/PDF/文字版。"
    return "請改用公司 IR/MOPS 官方 URL 或人工貼上文件文字。"


def company_filing_next_actions(per_ticker_results: list[dict]) -> list[dict]:
    actions = []
    for row in per_ticker_results:
        if row["status"] == "sufficient":
            continue
        action_type = {
            "retry_recommended": "retry_company_filing_search",
            "broader_search_recommended": "broaden_company_filing_search",
        }.get(row["status"], "manual_company_filing_import")
        actions.append(
            {
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "action": action_type,
                "reason": row["next_step"],
                "missing_required_types": row["missing_required_types"],
                "missing_recommended_types": row["missing_recommended_types"],
            }
        )
    return actions


def company_filing_gap_summary(per_ticker_results: list[dict]) -> dict:
    status_counts: dict[str, int] = {}
    for row in per_ticker_results:
        status = row.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    blocked = [
        row["ticker"]
        for row in per_ticker_results
        if row.get("status") in {"needs_manual_source", "broader_search_recommended"}
    ]
    retryable = [
        row["ticker"]
        for row in per_ticker_results
        if row.get("status") == "retry_recommended"
    ]
    if blocked:
        recommendation = "部分公司仍缺官方文件，需先補來源或擴大官方搜尋後再進入完整個股分析。"
    elif retryable:
        recommendation = "部分公司因資料源暫時錯誤而不足，建議稍後自動重試後再重跑分析。"
    else:
        recommendation = "公司文件補強狀態足夠，可進入完整個股分析。"
    return {
        "total_tickers": len(per_ticker_results),
        "status_counts": status_counts,
        "retryable_tickers": retryable,
        "blocked_tickers": blocked,
        "recommendation": recommendation,
    }
