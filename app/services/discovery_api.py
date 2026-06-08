from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, timedelta
from typing import Any

from app.core.time import today_taipei
from app.services.ingestion import IngestionPipeline
from app.services.persistence import NewsRepository
from app.services.topic_discovery import TopicDiscoveryService
from app.services.topic_discovery_models import TopicDiscoveryPlan


class DiscoveryApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        topic_discovery_service_cls: type[TopicDiscoveryService] = TopicDiscoveryService,
        topic_discovery_plan_cls: type[TopicDiscoveryPlan] = TopicDiscoveryPlan,
        news_repository_cls: type[NewsRepository] = NewsRepository,
        ingestion_pipeline_cls: type[IngestionPipeline] = IngestionPipeline,
        today_func: Callable[[], date] = today_taipei,
        discover_topic_with_timeout_func: Callable | None = None,
        discovery_fetch_settings_func: Callable | None = None,
        discovery_document_limit_func: Callable | None = None,
        run_topic_discovery_ingestion_func: Callable | None = None,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.topic_discovery_service_cls = topic_discovery_service_cls
        self.topic_discovery_plan_cls = topic_discovery_plan_cls
        self.news_repository_cls = news_repository_cls
        self.ingestion_pipeline_cls = ingestion_pipeline_cls
        self.today_func = today_func
        self.discover_topic_with_timeout_func = discover_topic_with_timeout_func
        self.discovery_fetch_settings_func = discovery_fetch_settings_func
        self.discovery_document_limit_func = discovery_document_limit_func
        self.run_topic_discovery_ingestion_func = run_topic_discovery_ingestion_func

    def topic_plan(self, payload: Any) -> dict:
        return self.topic_discovery_service_cls().discover(payload.topic)

    async def ingest(self, payload: Any) -> dict:
        if self.discover_topic_with_timeout_func is None:
            raise RuntimeError("discover_topic_with_timeout_func is required")
        if self.discovery_fetch_settings_func is None:
            raise RuntimeError("discovery_fetch_settings_func is required")
        if self.discovery_document_limit_func is None:
            raise RuntimeError("discovery_document_limit_func is required")
        if self.run_topic_discovery_ingestion_func is None:
            raise RuntimeError("run_topic_discovery_ingestion_func is required")

        service = self.topic_discovery_service_cls()
        discovery = await self.discover_topic_with_timeout_func(service, payload.topic)
        plan = self.topic_discovery_plan_cls.model_validate(discovery["plan"])
        limit_per_query, evidence_limit, max_queries = self.discovery_fetch_settings_func(payload)
        discovery_ingestion = await self.run_topic_discovery_ingestion_func(
            payload,
            service,
            plan,
            limit_per_query,
            evidence_limit,
            max_queries,
            document_limit=self.discovery_document_limit_func(payload, evidence_limit),
        )
        return {
            "discovery": discovery,
            "queries": discovery_ingestion["urls"],
            "ingestion": discovery_ingestion["ingestion_results"],
            "fixed_source_ingestion": discovery_ingestion["fixed_source_ingestion"],
            "dynamic_query_ingestion": discovery_ingestion["dynamic_query_ingestion"],
            "source_audit": discovery_ingestion["source_audit"],
            "candidate_whitelist": [
                candidate.model_dump() for candidate in discovery_ingestion["candidates"]
            ],
        }

    def candidate_whitelist(self, payload: Any) -> dict:
        service = self.topic_discovery_service_cls()
        discovery = service.discover(payload.topic)
        plan = self.topic_discovery_plan_cls.model_validate(discovery["plan"])
        end_date = self.today_func()
        start_date = end_date - timedelta(days=payload.lookback_days)
        with self.session_scope_factory() as session:
            documents = self.news_repository_cls(session).latest_documents(limit=max(200, payload.evidence_limit))
        documents = self.ingestion_pipeline_cls._filter_documents(
            documents,
            start_date,
            end_date,
            quality_filter=True,
        )
        candidates = service.validate_candidates(plan, documents)
        return {
            "discovery": discovery,
            "plan_quality": service.evaluate_plan_quality(plan).model_dump(),
            "candidate_whitelist": [candidate.model_dump() for candidate in candidates],
        }
