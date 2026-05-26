from __future__ import annotations

from datetime import date, timedelta

from app.core.time import today_taipei
from app.data_sources.company_filings import (
    RECOMMENDED_DOCUMENT_TYPES,
    REQUIRED_CORE_DOCUMENT_TYPES,
    CompanyFilingFetcher,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
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
        else:
            sources = (
                NewsSourceStore().enabled_sources()
                if enabled_sources_only
                else NewsSourceStore().load()
            )
            for source in sources:
                try:
                    source_documents = await fetcher.fetch_feed(
                        source.url,
                        source.publisher or source.name,
                        fetch_limit,
                    )
                    documents.extend(
                        self._filter_documents(source_documents, start_date, end_date, quality_filter)[:limit]
                    )
                except Exception as exc:
                    errors.append({"source": source.url, "error": str(exc)})

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
        return {"count": len(ingested), "items": ingested, "errors": errors}

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
            company_name = company.name if company else ""
            search_plans.append(fetcher.official_search_plan(ticker, company_name, document_types=document_types))
            company_documents, company_errors = await fetcher.fetch_discovery_documents(
                ticker,
                company_name,
                limit_per_query=limit_per_query,
                document_types=document_types,
            )
            documents.extend(company_documents)
            enriched_errors = [
                {
                    **error,
                    "ticker": ticker,
                    "company_name": company_name,
                    "category": classify_company_filing_error(error.get("error", "")),
                }
                for error in company_errors
            ]
            errors.extend(enriched_errors)
            per_ticker_results.append(
                company_filing_ticker_result(
                    ticker,
                    company_name,
                    company_documents,
                    target_document_types,
                    enriched_errors,
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
            "next_actions": company_filing_next_actions(per_ticker_results),
            "official_search_plans": search_plans,
            "source": "Google News company filing discovery",
        }

    async def pre_report_refresh(self, request: ReportRequest) -> dict:
        end_date = today_taipei()
        start_date = end_date - timedelta(days=request.lookback_days)
        tickers = self.mapper.filter_allowed_tickers(request.tickers)
        if not tickers:
            tickers = sorted(self.mapper.whitelist.allowed_tickers())
        news = await self.ingest_feeds(
            enabled_sources_only=True,
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


def company_filing_ticker_result(
    ticker: str,
    company_name: str,
    documents: list,
    target_document_types: tuple[str, ...],
    errors: list[dict],
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
    status = "sufficient" if documents and not missing_required else "needs_manual_source"
    return {
        "ticker": ticker,
        "company_name": company_name,
        "stored_count": len(documents),
        "document_types": document_types,
        "missing_required_types": missing_required,
        "missing_recommended_types": missing_recommended,
        "error_count": len(errors),
        "error_categories": sorted({error.get("category", "source_fetch_error") for error in errors}),
        "status": status,
        "next_step": company_filing_next_step(status, missing_required, missing_recommended),
    }


def company_filing_next_step(
    status: str,
    missing_required: list[str],
    missing_recommended: list[str],
) -> str:
    if status == "sufficient" and not missing_recommended:
        return "公司公開文件已足夠進入個股分析。"
    missing = missing_required or missing_recommended
    if missing:
        return "請補官方文件：" + "、".join(missing) + "；可使用 MOPS、TWSE/TPEx 或公司 IR 的 HTML/PDF/文字版。"
    return "請改用公司 IR/MOPS 官方 URL 或人工貼上文件文字。"


def company_filing_next_actions(per_ticker_results: list[dict]) -> list[dict]:
    actions = []
    for row in per_ticker_results:
        if row["status"] == "sufficient":
            continue
        actions.append(
            {
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "action": "manual_company_filing_import",
                "reason": row["next_step"],
                "missing_required_types": row["missing_required_types"],
                "missing_recommended_types": row["missing_recommended_types"],
            }
        )
    return actions
