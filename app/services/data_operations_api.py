from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.time import today_taipei
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.rag.vector_store import VectorStore
from app.services.analysis_run_repository import AnalysisRunRepository
from app.services.company_filing_repository import CompanyFilingRepository
from app.services.entity_mapping import EntityMapper
from app.services.ingestion import IngestionPipeline
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    ValuationMetricRepository,
)
from app.services.news_repository import NewsRepository
from app.services.report_files import prune_older_report_files_by_topic
from app.services.report_repository import ReportRepository
from app.services.schedule_config import ScheduleConfigStore


class DataOperationsApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        news_repository_cls: type[NewsRepository] = NewsRepository,
        market_repository_cls: type[MarketRepository] = MarketRepository,
        valuation_metric_repository_cls: type[
            ValuationMetricRepository
        ] = ValuationMetricRepository,
        company_filing_repository_cls: type[CompanyFilingRepository] = CompanyFilingRepository,
        financial_metric_repository_cls: type[
            FinancialMetricRepository
        ] = FinancialMetricRepository,
        analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
        report_repository_cls: type[ReportRepository] = ReportRepository,
        ingestion_pipeline_cls: type[IngestionPipeline] = IngestionPipeline,
        news_fetcher_cls: type[NewsFetcher] = NewsFetcher,
        vector_store_cls: type[VectorStore] = VectorStore,
        news_source_store_cls: type[NewsSourceStore] = NewsSourceStore,
        entity_mapper_cls: type[EntityMapper] = EntityMapper,
        schedule_config_store_cls: type[ScheduleConfigStore] = ScheduleConfigStore,
        report_file_retention_func: Callable[[], int] | None = None,
        today_func: Callable[[], date] = today_taipei,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.news_repository_cls = news_repository_cls
        self.market_repository_cls = market_repository_cls
        self.valuation_metric_repository_cls = valuation_metric_repository_cls
        self.company_filing_repository_cls = company_filing_repository_cls
        self.financial_metric_repository_cls = financial_metric_repository_cls
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.report_repository_cls = report_repository_cls
        self.ingestion_pipeline_cls = ingestion_pipeline_cls
        self.news_fetcher_cls = news_fetcher_cls
        self.vector_store_cls = vector_store_cls
        self.news_source_store_cls = news_source_store_cls
        self.entity_mapper_cls = entity_mapper_cls
        self.schedule_config_store_cls = schedule_config_store_cls
        self.report_file_retention_func = report_file_retention_func
        self.today_func = today_func

    def ingest_manual_news(
        self,
        *,
        title: str,
        text: str,
        publisher: str = "manual",
        published_at: date | None = None,
        url: str | None = None,
    ) -> dict:
        document = self.news_fetcher_cls.from_manual_text(
            title=title,
            text=text,
            publisher=publisher,
            published_at=published_at,
            url=url,
        )
        self.vector_store_cls().upsert_documents([document])
        matches = self.entity_mapper_cls().match_document(document)
        with self.session_scope_factory() as session:
            self.news_repository_cls(session).upsert_document(
                document,
                [match.model_dump(mode="json") for match in matches],
            )
        return {
            "document_id": document.id,
            "entity_matches": [match.model_dump() for match in matches],
        }

    def list_news(self, limit: int = 20) -> list[dict]:
        with self.session_scope_factory() as session:
            documents = self.news_repository_cls(session).latest_documents(limit)
        return [self._news_item(document) for document in documents]

    def list_news_sources(self) -> list[dict]:
        return [source.model_dump(mode="json") for source in self.news_source_store_cls().load()]

    async def fetch_news(
        self,
        *,
        url: str | None = None,
        publisher: str | None = None,
        limit: int = 10,
        enabled_sources_only: bool = True,
        topic: str | None = None,
    ) -> dict:
        return await self.ingestion_pipeline_cls().ingest_feeds(
            url=url,
            publisher=publisher,
            limit=limit,
            enabled_sources_only=enabled_sources_only,
            topic=topic,
        )

    async def refresh_market(
        self,
        *,
        tickers: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict:
        resolved_end_date = end_date or self.today_func()
        resolved_start_date = start_date or resolved_end_date - timedelta(days=14)
        return await self.ingestion_pipeline_cls().refresh_market(
            tickers,
            resolved_start_date,
            resolved_end_date,
        )

    async def refresh_fundamentals(
        self,
        *,
        tickers: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict:
        resolved_end_date = end_date or self.today_func()
        resolved_start_date = start_date or resolved_end_date - timedelta(days=365 * 6)
        pipeline = self.ingestion_pipeline_cls()
        financial_metrics = await pipeline.refresh_financial_metrics(
            tickers,
            resolved_start_date,
            resolved_end_date,
        )
        valuations = await pipeline.refresh_valuations(
            tickers,
            resolved_end_date - timedelta(days=30),
            resolved_end_date,
        )
        return {
            "financial_metrics": financial_metrics,
            "valuations": valuations,
        }

    def market_snapshots(self, tickers: str = "") -> list[dict]:
        mapper = self.entity_mapper_cls()
        requested = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        allowed = mapper.filter_allowed_tickers(
            requested or sorted(mapper.whitelist.allowed_tickers())
        )
        with self.session_scope_factory() as session:
            snapshots = self.market_repository_cls(session).latest_by_tickers(allowed)
        return [snapshot.model_dump(mode="json") for snapshot in snapshots]

    def market_cache_summary(self, tickers: str = "", limit_per_ticker: int = 2) -> dict:
        mapper = self.entity_mapper_cls()
        requested = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        allowed = mapper.filter_allowed_tickers(
            requested or sorted(mapper.whitelist.allowed_tickers())
        )
        with self.session_scope_factory() as session:
            snapshots = self.market_repository_cls(session).latest_by_tickers(allowed)
            valuations = self.valuation_metric_repository_cls(session).latest_by_tickers(allowed)
            filings = self.company_filing_repository_cls(session).latest_by_tickers(
                allowed,
                limit_per_ticker=max(1, min(int(limit_per_ticker), 10)),
            )
            financial_count = len(self.financial_metric_repository_cls(session).by_tickers(allowed))
        return {
            "tickers": allowed,
            "market_snapshots": [snapshot.model_dump(mode="json") for snapshot in snapshots],
            "valuations": [valuation.model_dump(mode="json") for valuation in valuations],
            "company_filings": [self._company_filing_item(filing) for filing in filings],
            "financial_metric_count": financial_count,
        }

    def get_schedule(self) -> dict:
        return self.schedule_config_store_cls().load().model_dump(mode="json")

    def update_schedule(self, config: Any) -> dict:
        saved = self.schedule_config_store_cls().save(config)
        return saved.model_dump(mode="json")

    def maintenance_cleanup(
        self,
        *,
        failed_runs: bool = False,
        orphan_report_refs: bool = False,
        stale_running_before: datetime | None = None,
        runs_before: datetime | None = None,
        reports_before: datetime | None = None,
        latest_reports_only: bool = False,
    ) -> dict:
        result = {
            "failed_runs_deleted": 0,
            "orphan_report_refs_cleared": 0,
            "stale_running_marked_failed": 0,
            "old_runs_deleted": 0,
            "old_reports_deleted": 0,
            "old_report_versions_deleted": 0,
            "old_report_files_deleted": 0,
            "report_retention_policy": "latest_per_topic",
        }
        with self.session_scope_factory() as session:
            runs = self.analysis_run_repository_cls(session)
            reports = self.report_repository_cls(session)
            if failed_runs:
                result["failed_runs_deleted"] = runs.delete_failed()
            if orphan_report_refs:
                result["orphan_report_refs_cleared"] = runs.clear_orphan_report_refs()
            if stale_running_before:
                result["stale_running_marked_failed"] = runs.mark_stale_running_failed(
                    stale_running_before,
                    "marked failed by maintenance cleanup",
                )
            if runs_before:
                result["old_runs_deleted"] = runs.delete_before(runs_before)
            if reports_before:
                result["old_reports_deleted"] = reports.delete_before(reports_before)
            if latest_reports_only:
                result["old_report_versions_deleted"] = reports.prune_older_by_topic()
        if latest_reports_only:
            result["old_report_files_deleted"] = self._prune_older_report_files()
        return result

    def _prune_older_report_files(self) -> int:
        if self.report_file_retention_func is not None:
            return self.report_file_retention_func()
        from app.core.config import get_settings

        return prune_older_report_files_by_topic(Path(get_settings().report_dir))

    @staticmethod
    def _news_item(document: Any) -> dict:
        return {
            "id": document.id,
            "title": document.title,
            "publisher": document.source.publisher,
            "published_at": document.source.published_at.isoformat()
            if document.source.published_at
            else None,
            "url": document.source.url,
        }

    @staticmethod
    def _company_filing_item(document: Any) -> dict:
        return {
            "id": getattr(document, "id", None),
            "ticker": getattr(document, "ticker", None),
            "company_name": getattr(document, "company_name", None),
            "document_type": getattr(document, "document_type", None),
            "title": getattr(document, "title", None),
            "publisher": getattr(getattr(document, "source", None), "publisher", None),
            "published_at": (
                document.source.published_at.isoformat()
                if getattr(getattr(document, "source", None), "published_at", None)
                else None
            ),
            "url": getattr(getattr(document, "source", None), "url", None),
        }
