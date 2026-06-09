from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from app.core.time import today_taipei
from app.data_sources.news import NewsFetcher
from app.db.session import session_scope
from app.rag.vector_store import VectorStore
from app.services.candidate_confidence import is_low_formal_confidence
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.entity_mapping import EntityMapper
from app.services.ingestion import IngestionPipeline
from app.services.news_repository import NewsRepository
from app.services.source_relevance import SourceRelevanceAnalyzer
from app.services.topic_discovery import TopicDiscoveryService
from app.services.topic_discovery_models import TopicDiscoveryPlan
from app.services.discovery_workflow_audit import (
    build_source_audit,
    query_intent_label,
    query_type_label,
    summarize_ingestion_stage,
    summarize_source_categories,
    summarize_source_intents,
    summarize_source_selection,
)
from app.services.discovery_workflow_settings import (
    discovery_analysis_mode,
    discovery_document_limit,
    discovery_effective_lookback_days,
    discovery_fetch_settings,
    discovery_market_history_days,
    discovery_valuation_history_days,
    is_deep_discovery,
)

__all__ = [
    "DiscoveryWorkflowService",
    "build_source_audit",
    "discovery_analysis_mode",
    "discovery_document_limit",
    "discovery_effective_lookback_days",
    "discovery_fetch_settings",
    "discovery_market_history_days",
    "discovery_query_budget",
    "discovery_valuation_history_days",
    "escalate_discovery_budget",
    "is_deep_discovery",
    "query_intent_label",
    "query_type_label",
    "should_escalate_discovery_budget",
    "should_supplement_discovery_sources",
    "source_selection_context",
    "summarize_candidate_support",
    "summarize_ingestion_stage",
    "summarize_source_categories",
    "summarize_source_intents",
    "summarize_source_selection",
]


def summarize_candidate_support(candidates) -> dict:
    total = len(candidates)
    supported = sum(1 for candidate in candidates if candidate.status == "evidence_supported")
    weak = sum(1 for candidate in candidates if candidate.status == "weak_evidence")
    unsupported = sum(1 for candidate in candidates if candidate.status == "needs_evidence")
    unavailable = sum(1 for candidate in candidates if candidate.status == "evidence_unavailable")
    limited = sum(1 for candidate in candidates if candidate.status == "evidence_limited")
    supported_scores = [
        int(candidate.evidence_confidence_score or 0)
        for candidate in candidates
        if candidate.status == "evidence_supported"
    ]
    exploration_supported_ratio = supported / total if total else 0
    return {
        "total": total,
        "supported": supported,
        "weak": weak,
        "unsupported": unsupported,
        "unavailable": unavailable,
        "limited": limited,
        "supported_ratio": exploration_supported_ratio,
        "exploration_supported_ratio": exploration_supported_ratio,
        "formal_supported_ratio": 1.0 if supported else 0,
        "formal_confidence_avg": round(sum(supported_scores) / len(supported_scores), 1)
        if supported_scores
        else None,
        "formal_confidence_min": min(supported_scores) if supported_scores else None,
        "formal_low_confidence_count": sum(
            1 for score in supported_scores if is_low_formal_confidence(score)
        ),
    }


def should_supplement_discovery_sources(source_audit: dict, candidate_support: dict) -> bool:
    plan_quality = source_audit.get("plan_quality") or {}
    query_quality = plan_quality.get("query_quality") or {}
    if plan_quality and plan_quality.get("status") != "ready":
        return True
    if int(query_quality.get("generic_query_count") or 0) > 0:
        return True
    source_relevance = source_audit.get("source_relevance") or {}
    if int(source_relevance.get("missing_subtopic_count") or 0) > 0:
        return True
    if candidate_support["total"] == 0:
        return source_audit["dynamic_queries"]["stored_count"] < 8
    supported_ratio = float(candidate_support.get("supported_ratio") or 0)
    target_supported_ratio = 0.75 if source_audit.get("analysis_mode") == "deep" else 0.65
    if supported_ratio < target_supported_ratio:
        return True
    candidate_gap_count = sum(
        int(candidate_support.get(key) or 0)
        for key in ("weak", "unsupported", "limited", "unavailable")
    )
    if candidate_gap_count >= max(2, int(candidate_support["total"] * 0.2)):
        return True
    return source_audit["dynamic_queries"]["stored_count"] < 12


def discovery_query_budget(
    max_queries: int, analysis_mode: str = "standard", deep_analysis: bool = False
) -> dict:
    mode = "deep" if deep_analysis else analysis_mode
    settings = {
        "fast": {
            "initial_floor": 8,
            "initial_ratio": 0.65,
            "rounds": 1,
            "batch": 6,
            "no_gain_stop": 1,
        },
        "standard": {
            "initial_floor": 12,
            "initial_ratio": 0.55,
            "rounds": 3,
            "batch": 10,
            "no_gain_stop": 2,
        },
        "deep": {
            "initial_floor": 24,
            "initial_ratio": 0.45,
            "rounds": 4,
            "batch": 12,
            "no_gain_stop": 2,
        },
    }.get(mode, {})
    initial_queries = max(
        settings.get("initial_floor", 12), int(max_queries * settings.get("initial_ratio", 0.55))
    )
    return {
        "initial_queries": min(max_queries, initial_queries),
        "supplemental_queries": max(0, max_queries - initial_queries),
        "supplemental_rounds": settings.get("rounds", 3),
        "supplemental_batch_size": settings.get("batch", 10),
        "no_gain_stop_rounds": settings.get("no_gain_stop", 2),
        "analysis_mode": mode,
    }


def should_escalate_discovery_budget(
    source_audit: dict,
    candidate_support: dict,
    current_budget: dict,
) -> bool:
    if current_budget.get("escalated"):
        return False
    if current_budget.get("analysis_mode") == "deep":
        return False
    plan_quality = source_audit.get("plan_quality") or {}
    source_relevance = source_audit.get("source_relevance") or {}
    if plan_quality.get("status") == "insufficient":
        return True
    if int(source_relevance.get("missing_subtopic_count") or 0) >= 2:
        return True
    if int(source_relevance.get("weak_subtopic_count") or 0) >= 3:
        return True
    if (
        int(candidate_support.get("total") or 0) > 0
        and float(candidate_support.get("supported_ratio") or 0) < 0.35
    ):
        return True
    return False


def escalate_discovery_budget(budget: dict, max_queries: int) -> dict:
    supplemental_rounds = max(int(budget.get("supplemental_rounds") or 0), 5)
    supplemental_batch_size = max(int(budget.get("supplemental_batch_size") or 0), 12)
    initial_queries = int(budget.get("initial_queries") or 0)
    return {
        **budget,
        "analysis_mode": f"{budget.get('analysis_mode', 'standard')}_auto_escalated",
        "supplemental_rounds": supplemental_rounds,
        "supplemental_batch_size": supplemental_batch_size,
        "supplemental_queries": max(0, max_queries - initial_queries),
        "no_gain_stop_rounds": max(int(budget.get("no_gain_stop_rounds") or 0), 2),
        "escalated": True,
        "escalation_reason": "plan_or_source_coverage_gap",
    }


def source_selection_context(topic: str, plan: TopicDiscoveryPlan | None = None) -> str:
    terms = [topic]
    if plan:
        for subtopic in plan.subtopics:
            terms.extend(
                [
                    subtopic.name,
                    subtopic.objective,
                    " ".join(subtopic.required_evidence[:3]),
                    " ".join(subtopic.risk_focus[:3]),
                    " ".join(subtopic.source_intents[:3]),
                ]
            )
        for candidate in plan.candidate_companies:
            terms.extend(
                [candidate.name, candidate.segment, " ".join(candidate.evidence_keywords[:4])]
            )
    return " ".join(term for term in terms if term)


class DiscoveryWorkflowService:
    def __init__(
        self,
        session_scope_factory: Callable = session_scope,
        ingestion_pipeline_cls=IngestionPipeline,
        news_repository_cls=NewsRepository,
        news_fetcher_cls=NewsFetcher,
        entity_mapper_cls=EntityMapper,
        vector_store_cls=VectorStore,
        source_relevance_analyzer_cls=SourceRelevanceAnalyzer,
        candidate_revalidation_service: CandidateRevalidationService | None = None,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.ingestion_pipeline_cls = ingestion_pipeline_cls
        self.news_repository_cls = news_repository_cls
        self.news_fetcher_cls = news_fetcher_cls
        self.entity_mapper_cls = entity_mapper_cls
        self.vector_store_cls = vector_store_cls
        self.source_relevance_analyzer_cls = source_relevance_analyzer_cls
        self.candidate_revalidation_service = (
            candidate_revalidation_service
            or CandidateRevalidationService(
                session_scope_factory=session_scope_factory,
                news_repository_cls=news_repository_cls,
            )
        )

    async def ingest_dynamic_news_urls(
        self,
        urls: list[str],
        limit_per_query: int,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        if not urls:
            return []

        fetch_limit = limit_per_query * 6
        semaphore = asyncio.Semaphore(6)
        fetcher = self.news_fetcher_cls()

        async def fetch_one(url: str) -> dict:
            async with semaphore:
                documents = []
                errors = []
                try:
                    fetched = await asyncio.wait_for(
                        fetcher.fetch_feed(url, publisher=None, limit=fetch_limit),
                        timeout=10,
                    )
                    documents = self.ingestion_pipeline_cls._filter_documents(
                        fetched,
                        start_date,
                        end_date,
                        quality_filter=True,
                    )[:limit_per_query]
                except Exception as exc:
                    errors.append({"source": url, "error": str(exc) or exc.__class__.__name__})
                return {"url": url, "documents": documents, "errors": errors}

        fetched_results = await asyncio.gather(*(fetch_one(url) for url in urls))
        all_documents = self.ingestion_pipeline_cls._dedupe_documents(
            [document for result in fetched_results for document in result["documents"]]
        )
        matches_by_id = {}
        if all_documents:
            mapper = self.entity_mapper_cls()
            self.vector_store_cls().upsert_documents(all_documents)
            with self.session_scope_factory() as session:
                repository = self.news_repository_cls(session)
                for document in all_documents:
                    matches = mapper.match_document(document)
                    matches_payload = [match.model_dump(mode="json") for match in matches]
                    repository.upsert_document(document, matches_payload)
                    matches_by_id[document.id] = matches_payload

        ingestion_results = []
        for result in fetched_results:
            documents = self.ingestion_pipeline_cls._dedupe_documents(result["documents"])
            ingested = [
                {
                    "id": document.id,
                    "title": document.title,
                    "publisher": document.source.publisher,
                    "published_at": document.source.published_at.isoformat()
                    if document.source.published_at
                    else None,
                    "entity_matches": matches_by_id.get(document.id, []),
                }
                for document in documents
            ]
            ingestion_results.append(
                {
                    "count": len(ingested),
                    "items": ingested,
                    "errors": result["errors"],
                    "source_results": [],
                    "source_category_counts": {},
                    "source_selection": {
                        "mode": "single_url",
                        "selected_count": 1,
                        "available_count": 1,
                    },
                }
            )
        return ingestion_results

    async def run_topic_discovery_ingestion(
        self,
        payload: Any,
        service: TopicDiscoveryService,
        plan: TopicDiscoveryPlan,
        limit_per_query: int,
        evidence_limit: int,
        max_queries: int,
        document_limit: int,
    ) -> dict:
        budget = discovery_query_budget(
            max_queries,
            analysis_mode=discovery_analysis_mode(payload),
            deep_analysis=payload.deep_analysis,
        )
        plan_quality = service.evaluate_plan_quality(plan)
        query_metadata = service.google_news_urls(
            plan,
            include_international=payload.include_international,
            max_urls=budget["initial_queries"],
            topic=payload.topic,
            include_metadata=True,
        )
        urls = [item["url"] for item in query_metadata]
        end_date = today_taipei()
        lookback_days = discovery_effective_lookback_days(payload)
        start_date = end_date - timedelta(days=lookback_days)
        fixed_source_ingestion = await self.ingestion_pipeline_cls().ingest_feeds(
            enabled_sources_only=True,
            topic=source_selection_context(payload.topic, plan),
            limit=limit_per_query,
            start_date=start_date,
            end_date=end_date,
        )
        dynamic_query_ingestion = await self.ingest_dynamic_news_urls(
            urls,
            limit_per_query,
            start_date,
            end_date,
        )
        remediation_rounds = []
        no_gain_rounds = 0
        remediation_stop_reason = "coverage_sufficient"
        candidates = []
        candidate_support = {
            "total": 0,
            "supported": 0,
            "weak": 0,
            "unsupported": 0,
            "supported_ratio": 0,
        }
        source_audit = build_source_audit(
            payload,
            urls,
            fixed_source_ingestion,
            dynamic_query_ingestion,
            limit_per_query,
            evidence_limit,
            max_queries,
            query_metadata,
        )
        source_audit["plan_quality"] = plan_quality.model_dump()

        for round_index in range(budget["supplemental_rounds"] + 1):
            with self.session_scope_factory() as session:
                documents = self.news_repository_cls(session).latest_documents(
                    limit=max(document_limit, evidence_limit)
                )
            documents = self.ingestion_pipeline_cls._filter_documents(
                documents,
                start_date,
                end_date,
                quality_filter=True,
            )
            candidates = service.validate_candidates(plan, documents)
            source_relevance = self.source_relevance_analyzer_cls(service).analyze(
                plan, documents, limit=document_limit
            )
            dynamic_entity_backfill = (
                self.candidate_revalidation_service.persist_candidate_entity_matches(
                    plan,
                    candidates,
                    documents,
                )
            )
            candidate_support = summarize_candidate_support(candidates)
            source_audit = build_source_audit(
                payload,
                urls,
                fixed_source_ingestion,
                dynamic_query_ingestion,
                limit_per_query,
                evidence_limit,
                max_queries,
                query_metadata,
            )
            source_audit["plan_quality"] = plan_quality.model_dump()
            source_audit["source_relevance"] = source_relevance
            if should_escalate_discovery_budget(source_audit, candidate_support, budget):
                budget = escalate_discovery_budget(budget, max_queries)
            if not should_supplement_discovery_sources(source_audit, candidate_support):
                remediation_stop_reason = "coverage_sufficient"
                break
            remaining_queries = max_queries - len(urls)
            if remaining_queries <= 0 or round_index >= budget["supplemental_rounds"]:
                remediation_stop_reason = "query_budget_exhausted"
                break
            supplemental_metadata = service.supplemental_google_news_query_metadata(
                plan,
                candidates,
                include_international=payload.include_international,
                max_urls=min(remaining_queries, budget["supplemental_batch_size"]),
                existing_urls=urls,
                missing_subtopics=service.missing_subtopic_names(source_relevance),
            )
            supplemental_urls = [item["url"] for item in supplemental_metadata]
            if not supplemental_urls:
                remediation_stop_reason = "no_supplemental_queries"
                break
            supplemental_ingestion = await self.ingest_dynamic_news_urls(
                supplemental_urls,
                limit_per_query,
                start_date,
                end_date,
            )
            supplemental_summary = summarize_ingestion_stage(supplemental_ingestion)
            if supplemental_summary["stored_count"] <= 0:
                no_gain_rounds += 1
            else:
                no_gain_rounds = 0
            urls.extend(supplemental_urls)
            query_metadata.extend(supplemental_metadata)
            dynamic_query_ingestion.extend(supplemental_ingestion)
            remediation_rounds.append(
                {
                    "round": round_index + 1,
                    "query_count": len(supplemental_urls),
                    "stored_count": supplemental_summary["stored_count"],
                    "reason": "low_candidate_or_source_coverage",
                    "no_gain_rounds": no_gain_rounds,
                }
            )
            if no_gain_rounds >= int(budget.get("no_gain_stop_rounds") or 2):
                remediation_stop_reason = "no_new_sources"
                break

        source_audit = build_source_audit(
            payload,
            urls,
            fixed_source_ingestion,
            dynamic_query_ingestion,
            limit_per_query,
            evidence_limit,
            max_queries,
            query_metadata,
        )
        source_audit["plan_quality"] = service.evaluate_plan_quality(plan).model_dump()
        source_audit["candidate_support"] = candidate_support
        source_audit["source_relevance"] = source_relevance
        source_audit["remediation"] = {
            "supplemented": bool(remediation_rounds),
            "reason": remediation_stop_reason,
            "rounds": remediation_rounds,
            "supplemental_query_count": sum(
                round_item["query_count"] for round_item in remediation_rounds
            ),
            "supplemental_stored_count": sum(
                round_item["stored_count"] for round_item in remediation_rounds
            ),
            "stopped_by_no_gain": bool(
                remediation_rounds
                and remediation_rounds[-1].get("no_gain_rounds", 0)
                >= int(budget.get("no_gain_stop_rounds") or 2)
            ),
        }
        source_audit["query_budget"] = budget
        source_audit["dynamic_entity_backfill"] = dynamic_entity_backfill
        return {
            "urls": urls,
            "start_date": start_date,
            "end_date": end_date,
            "documents": documents,
            "candidates": candidates,
            "fixed_source_ingestion": fixed_source_ingestion,
            "dynamic_query_ingestion": dynamic_query_ingestion,
            "ingestion_results": [fixed_source_ingestion, *dynamic_query_ingestion],
            "source_audit": source_audit,
        }

    async def discover_topic_with_timeout(
        self,
        service: TopicDiscoveryService,
        topic: str,
        timeout: int = 75,
    ) -> dict:
        fallback_plan = TopicDiscoveryService._fallback_plan(topic)
        fallback_quality = service.evaluate_plan_quality(fallback_plan)
        try:
            discovery = await asyncio.wait_for(
                asyncio.to_thread(service.discover, topic), timeout=timeout
            )
        except Exception as exc:
            return {
                "topic": topic,
                "fallback": True,
                "message": f"AI topic discovery timed out or failed; deterministic fallback was applied: {exc}",
                "plan": fallback_plan.model_dump(),
                "plan_quality": fallback_quality.model_dump(),
                "initial_plan_quality": service.evaluate_plan_quality(
                    TopicDiscoveryPlan()
                ).model_dump(),
                "repair_attempted": False,
                "repair_applied": False,
                "fallback_plan_applied": True,
            }

        plan = TopicDiscoveryPlan.model_validate(discovery.get("plan") or {})
        plan_quality = service.evaluate_plan_quality(plan)
        if plan_quality.status == "ready":
            return discovery

        if fallback_quality.score > plan_quality.score:
            return {
                **discovery,
                "fallback": True,
                "message": "AI topic discovery was incomplete; deterministic fallback provided broader coverage.",
                "plan": fallback_plan.model_dump(),
                "plan_quality": fallback_quality.model_dump(),
                "fallback_plan_applied": True,
            }
        return discovery
