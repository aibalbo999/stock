from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from app.data_sources.company_filing_discovery import (
    filing_quality_score,
    filing_source_tier,
)
from app.data_sources.company_filings import CompanyFilingFetcher
from app.services.entity_mapping import EntityMapper
from app.services.ingestion import IngestionPipeline
from app.services.persistence import CompanyFilingRepository
from app.rag.vector_store import VectorStore


class CompanyFilingApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        company_filing_fetcher_cls: type[CompanyFilingFetcher] = CompanyFilingFetcher,
        company_filing_repository_cls: type[CompanyFilingRepository] = CompanyFilingRepository,
        vector_store_cls: type[VectorStore] = VectorStore,
        entity_mapper_cls: type[EntityMapper] = EntityMapper,
        ingestion_pipeline_cls: type[IngestionPipeline] = IngestionPipeline,
        filing_source_tier_func: Callable[[Any], str] = filing_source_tier,
        filing_quality_score_func: Callable[[Any, str, str], int] = filing_quality_score,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.company_filing_fetcher_cls = company_filing_fetcher_cls
        self.company_filing_repository_cls = company_filing_repository_cls
        self.vector_store_cls = vector_store_cls
        self.entity_mapper_cls = entity_mapper_cls
        self.ingestion_pipeline_cls = ingestion_pipeline_cls
        self.filing_source_tier_func = filing_source_tier_func
        self.filing_quality_score_func = filing_quality_score_func

    def ingest_manual(
        self,
        *,
        ticker: str,
        title: str,
        text: str,
        company_name: str = "",
        document_type: str = "company_disclosure",
        publisher: str = "manual company filing",
        published_at: date | None = None,
        url: str | None = None,
    ) -> dict:
        document = self.company_filing_fetcher_cls.from_manual_text(
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
            title=title,
            text=text,
            publisher=publisher,
            published_at=published_at,
            url=url,
        )
        return self.persist_document(document)

    async def ingest_from_url(
        self,
        *,
        url: str,
        ticker: str,
        company_name: str = "",
        document_type: str = "company_disclosure",
        publisher: str | None = None,
        published_at: date | None = None,
    ) -> dict:
        document = await self.company_filing_fetcher_cls().fetch_url_document(
            url=url,
            ticker=ticker,
            company_name=company_name,
            document_type=document_type,
            publisher=publisher,
            published_at=published_at,
        )
        return self.persist_document(document)

    def persist_document(self, document: Any) -> dict:
        news_document = self.company_filing_repository_cls.to_news_document(document)
        self.vector_store_cls().upsert_documents([news_document])
        with self.session_scope_factory() as session:
            self.company_filing_repository_cls(session).upsert_document(document)
        return self._document_quality_summary(document)

    async def fetch_company_filings(self, tickers: list[str]) -> dict:
        return await self.ingestion_pipeline_cls().ingest_company_filings(
            tickers,
            limit_per_query=3,
            filter_allowed=bool(tickers),
        )

    def list_company_filings(self, tickers: str = "", limit_per_ticker: int = 5) -> list[dict]:
        requested = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        mapper = self.entity_mapper_cls()
        allowed = mapper.filter_allowed_tickers(requested or sorted(mapper.whitelist.allowed_tickers()))
        with self.session_scope_factory() as session:
            documents = self.company_filing_repository_cls(session).latest_by_tickers(
                allowed,
                limit_per_ticker=max(1, min(limit_per_ticker, 20)),
            )
        return [self._document_list_item(document) for document in documents]

    def _document_quality_summary(self, document: Any) -> dict:
        return {
            "document_id": document.id,
            "ticker": document.ticker,
            "document_type": document.document_type,
            "source_tier": self.filing_source_tier_func(document),
            "quality_score": self.filing_quality_score_func(
                document,
                document.ticker,
                document.company_name or "",
            ),
        }

    def _document_list_item(self, document: Any) -> dict:
        return {
            "id": document.id,
            "ticker": document.ticker,
            "company_name": document.company_name,
            "document_type": document.document_type,
            "title": document.title,
            "publisher": document.source.publisher,
            "source_tier": self.filing_source_tier_func(document),
            "quality_score": self.filing_quality_score_func(
                document,
                document.ticker,
                document.company_name or "",
            ),
            "published_at": document.source.published_at.isoformat()
            if document.source.published_at
            else None,
            "url": document.source.url,
        }
