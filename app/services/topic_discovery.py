from __future__ import annotations

from app.models.schemas import NewsDocument
from app.services import (
    topic_discovery_candidates,
    topic_discovery_enrichment,
    topic_discovery_fallbacks,
    topic_discovery_parser,
    topic_discovery_prompts,
    topic_discovery_quality,
    topic_discovery_queries,
)
from app.services.llm_client import LLMClient
from app.services.topic_discovery_models import (
    CandidateCompany as CandidateCompany,
    DiscoveryPlanQuality as DiscoveryPlanQuality,
    DiscoverySubtopic as DiscoverySubtopic,
    TopicDiscoveryPlan as TopicDiscoveryPlan,
    ValidatedCandidate as ValidatedCandidate,
)


class TopicDiscoveryService:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def discover(self, topic: str) -> dict:
        result = self.llm.generate_with_metadata(self._prompt(topic))
        if result.fallback:
            fallback_plan = self._fallback_plan(topic)
            fallback_quality = self.evaluate_plan_quality(fallback_plan)
            return {
                "topic": topic,
                "fallback": True,
                "message": result.text,
                "plan": fallback_plan.model_dump(),
                "plan_quality": fallback_quality.model_dump(),
                "initial_plan_quality": self.evaluate_plan_quality(
                    TopicDiscoveryPlan()
                ).model_dump(),
                "repair_attempted": False,
                "repair_applied": False,
                "fallback_plan_applied": True,
            }
        try:
            plan = self.enrich_plan(self.parse_plan(result.text), topic=topic)
        except ValueError as exc:
            fallback_plan = self._fallback_plan(topic)
            fallback_quality = self.evaluate_plan_quality(fallback_plan)
            return {
                "topic": topic,
                "fallback": True,
                "message": f"AI discovery JSON parse failed: {exc}",
                "raw_preview": result.text[:500],
                "plan": fallback_plan.model_dump(),
                "plan_quality": fallback_quality.model_dump(),
                "initial_plan_quality": self.evaluate_plan_quality(
                    TopicDiscoveryPlan()
                ).model_dump(),
                "repair_attempted": False,
                "repair_applied": False,
                "fallback_plan_applied": True,
            }
        initial_quality = self.evaluate_plan_quality(plan)
        repair = None
        final_plan = plan
        final_quality = initial_quality
        if initial_quality.status != "ready":
            repair = self.repair_plan(topic, plan, initial_quality)
            if repair is not None and repair["quality"].score >= initial_quality.score:
                final_plan = repair["plan"]
                final_quality = repair["quality"]
        fallback_plan_applied = False
        if final_quality.status == "insufficient":
            fallback_plan = self._fallback_plan(topic)
            fallback_quality = self.evaluate_plan_quality(fallback_plan)
            if fallback_quality.score > final_quality.score:
                final_plan = fallback_plan
                final_quality = fallback_quality
                fallback_plan_applied = True
        return {
            "topic": topic,
            "fallback": fallback_plan_applied,
            "model": result.model,
            "key_index": result.key_index,
            "plan": final_plan.model_dump(),
            "plan_quality": final_quality.model_dump(),
            "initial_plan_quality": initial_quality.model_dump(),
            "repair_attempted": initial_quality.status != "ready",
            "repair_applied": final_plan is not plan,
            "fallback_plan_applied": fallback_plan_applied,
            "repair_model": repair["model"] if repair else None,
            "repair_key_index": repair["key_index"] if repair else None,
        }

    def repair_plan(
        self,
        topic: str,
        plan: TopicDiscoveryPlan,
        quality: DiscoveryPlanQuality,
    ) -> dict | None:
        result = self.llm.generate_with_metadata(self._repair_prompt(topic, plan, quality))
        if result.fallback:
            return None
        try:
            repaired_plan = self.enrich_plan(self.parse_plan(result.text), topic=topic)
        except ValueError:
            return None
        return {
            "plan": repaired_plan,
            "quality": self.evaluate_plan_quality(repaired_plan),
            "model": result.model,
            "key_index": result.key_index,
        }

    @staticmethod
    def _fallback_plan(topic: str) -> TopicDiscoveryPlan:
        return topic_discovery_fallbacks.fallback_plan(topic)

    @staticmethod
    def _generic_exploration_plan(topic: str) -> TopicDiscoveryPlan:
        return topic_discovery_fallbacks.generic_exploration_plan(topic)

    @staticmethod
    def _generic_anchor_candidates(topic: str) -> list[CandidateCompany]:
        return topic_discovery_fallbacks.generic_anchor_candidates(topic)

    @staticmethod
    def _memory_fallback_plan(topic: str) -> TopicDiscoveryPlan:
        return topic_discovery_fallbacks.memory_fallback_plan(topic)

    @staticmethod
    def _is_robotics_topic(topic: str) -> bool:
        return topic_discovery_fallbacks.is_robotics_topic(topic)

    @staticmethod
    def _is_memory_topic(topic: str) -> bool:
        return topic_discovery_fallbacks.is_memory_topic(topic)

    @staticmethod
    def _is_memory_plan(plan: TopicDiscoveryPlan) -> bool:
        return topic_discovery_quality.is_memory_plan(plan)

    @staticmethod
    def _robotics_fallback_plan(topic: str) -> TopicDiscoveryPlan:
        return topic_discovery_fallbacks.robotics_fallback_plan(topic)

    @staticmethod
    def evaluate_plan_quality(plan: TopicDiscoveryPlan) -> DiscoveryPlanQuality:
        return topic_discovery_quality.evaluate_plan_quality(plan)

    @staticmethod
    def _requires_broad_candidate_pool(plan: TopicDiscoveryPlan) -> bool:
        return topic_discovery_quality.requires_broad_candidate_pool(plan)

    @staticmethod
    def _plan_theme_coverage(plan: TopicDiscoveryPlan) -> dict[str, bool]:
        return topic_discovery_quality.plan_theme_coverage(plan)

    @staticmethod
    def _keyword_in_text(text: str, keyword: str) -> bool:
        return topic_discovery_quality.keyword_in_text(text, keyword)

    @staticmethod
    def _requires_upstream_material_coverage(
        plan: TopicDiscoveryPlan, topic: str | None = None
    ) -> bool:
        return topic_discovery_quality.requires_upstream_material_coverage(plan, topic=topic)

    @staticmethod
    def _is_generic_exploration_plan(plan: TopicDiscoveryPlan) -> bool:
        return topic_discovery_quality.is_generic_exploration_plan(plan)

    @staticmethod
    def _has_upstream_material_coverage(plan: TopicDiscoveryPlan) -> bool:
        return topic_discovery_quality.has_upstream_material_coverage(plan)

    @staticmethod
    def _plan_search_text(plan: TopicDiscoveryPlan) -> str:
        return topic_discovery_quality.plan_search_text(plan)

    @staticmethod
    def _plan_query_quality(plan: TopicDiscoveryPlan) -> dict:
        return topic_discovery_quality.plan_query_quality(plan)

    @staticmethod
    def _query_aligns_subtopic(query: str, subtopic: DiscoverySubtopic) -> bool:
        return topic_discovery_queries.query_aligns_subtopic(query, subtopic)

    @staticmethod
    def _research_terms(subtopic: DiscoverySubtopic) -> list[str]:
        return topic_discovery_queries.research_terms(subtopic)

    @staticmethod
    def _meaningful_tokens(text: str) -> list[str]:
        return topic_discovery_queries.meaningful_tokens(text)

    @staticmethod
    def _is_generic_query(query: str) -> bool:
        return topic_discovery_queries.is_generic_query(query)

    @staticmethod
    def _is_noise_term(term: str) -> bool:
        return topic_discovery_queries.is_noise_term(term)

    def google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        include_international: bool = True,
        max_urls: int | None = None,
        topic: str | None = None,
        include_metadata: bool = False,
    ) -> list[str] | list[dict]:
        return topic_discovery_queries.google_news_urls(
            plan,
            include_international=include_international,
            max_urls=max_urls,
            topic=topic,
            include_metadata=include_metadata,
            evaluate_plan_quality=self.evaluate_plan_quality,
            infer_source_intents=self.infer_source_intents,
        )

    @staticmethod
    def _query_item(
        query: str,
        source_type: str,
        hypothesis: str,
        evidence_type: str,
        source_intent: str,
    ) -> dict:
        return topic_discovery_queries.query_item(
            query, source_type, hypothesis, evidence_type, source_intent
        )

    @staticmethod
    def _subtopic_hypothesis(subtopic: DiscoverySubtopic) -> str:
        return topic_discovery_queries.subtopic_hypothesis(subtopic)

    @staticmethod
    def _evidence_type(required_evidence: list[str], risk_focus: list[str]) -> str:
        return topic_discovery_queries.evidence_type(required_evidence, risk_focus)

    @staticmethod
    def _primary_source_intent(subtopic: DiscoverySubtopic) -> str:
        return topic_discovery_queries.primary_source_intent(
            subtopic,
            infer_source_intents=TopicDiscoveryService.infer_source_intents,
        )

    @staticmethod
    def _query_language(query: str) -> str:
        return topic_discovery_queries.query_language(query)

    @staticmethod
    def coverage_gap_queries(topic: str, quality: DiscoveryPlanQuality) -> list[str]:
        return topic_discovery_queries.coverage_gap_queries(topic, quality)

    @staticmethod
    def query_quality_gap_queries(
        topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality
    ) -> list[str]:
        return topic_discovery_queries.query_quality_gap_queries(topic, plan, quality)

    def supplemental_google_news_urls(
        self,
        plan: TopicDiscoveryPlan,
        validated_candidates: list[ValidatedCandidate],
        include_international: bool = True,
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        return topic_discovery_queries.supplemental_google_news_urls(
            plan,
            validated_candidates,
            include_international=include_international,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

    def supplemental_google_news_query_metadata(
        self,
        plan: TopicDiscoveryPlan,
        validated_candidates: list[ValidatedCandidate],
        include_international: bool = True,
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
        missing_subtopics: list[str] | None = None,
    ) -> list[dict]:
        return topic_discovery_queries.supplemental_google_news_query_metadata(
            plan,
            validated_candidates,
            include_international=include_international,
            max_urls=max_urls,
            existing_urls=existing_urls,
            missing_subtopics=missing_subtopics,
        )

    @staticmethod
    def _candidate_query_items(
        candidate: CandidateCompany, include_international: bool = True
    ) -> list[dict]:
        return topic_discovery_queries.candidate_query_items(
            candidate,
            include_international=include_international,
        )

    @staticmethod
    def _supplemental_candidate_query_items(
        candidate: CandidateCompany,
        include_international: bool = True,
    ) -> list[dict]:
        return topic_discovery_queries.supplemental_candidate_query_items(
            candidate,
            include_international=include_international,
        )

    @staticmethod
    def _round_robin_query_groups(groups: list[list[dict]]) -> list[dict]:
        return topic_discovery_queries.round_robin_query_groups(groups)

    @staticmethod
    def _dedupe_query_items(items: list[dict]) -> list[dict]:
        return topic_discovery_queries.dedupe_query_items(items)

    @staticmethod
    def _dedupe_query_metadata(
        items: list[dict],
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[dict]:
        return topic_discovery_queries.dedupe_query_metadata(
            items,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

    @staticmethod
    def missing_subtopic_names(source_relevance: dict) -> list[str]:
        return topic_discovery_queries.missing_subtopic_names(source_relevance)

    @staticmethod
    def _google_news_urls_from_queries(
        queries: list[str],
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[str]:
        return topic_discovery_queries.google_news_urls_from_queries(
            queries,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

    @staticmethod
    def _google_news_metadata_from_queries(
        queries: list[str],
        source_type: str,
        hypothesis: str,
        evidence_type: str,
        source_intent: str = "industry_news",
        max_urls: int | None = None,
        existing_urls: list[str] | None = None,
    ) -> list[dict]:
        return topic_discovery_queries.google_news_metadata_from_queries(
            queries,
            source_type,
            hypothesis,
            evidence_type,
            source_intent=source_intent,
            max_urls=max_urls,
            existing_urls=existing_urls,
        )

    @staticmethod
    def _international_context_queries() -> list[str]:
        return topic_discovery_queries.international_context_queries()

    def validate_candidates(
        self,
        plan: TopicDiscoveryPlan,
        documents: list[NewsDocument],
    ) -> list[ValidatedCandidate]:
        return topic_discovery_candidates.validate_candidates(plan, documents)

    @staticmethod
    def _candidate_entity_terms(candidate: CandidateCompany) -> list[str]:
        return topic_discovery_candidates.candidate_entity_terms(candidate)

    @staticmethod
    def _candidate_context_terms(
        candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None
    ) -> list[str]:
        return topic_discovery_candidates.candidate_context_terms(candidate, plan)

    @staticmethod
    def _is_robotics_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> bool:
        return topic_discovery_quality.is_robotics_plan(plan, topic=topic)

    @staticmethod
    def _plan_or_candidate_mentions_robotics(
        candidate: CandidateCompany, plan: TopicDiscoveryPlan | None = None
    ) -> bool:
        return topic_discovery_candidates.plan_or_candidate_mentions_robotics(candidate, plan)

    @staticmethod
    def _context_phrases(text: str) -> list[str]:
        return topic_discovery_candidates.context_phrases(text)

    @staticmethod
    def _has_entity_and_context(
        haystack: str, entity_terms: list[str], context_terms: list[str]
    ) -> bool:
        return topic_discovery_candidates.has_entity_and_context(
            haystack, entity_terms, context_terms
        )

    @staticmethod
    def _has_entity_and_context_nearby(
        haystack: str,
        entity_terms: list[str],
        context_terms: list[str],
        window: int = 900,
    ) -> bool:
        return topic_discovery_candidates.has_entity_and_context_nearby(
            haystack,
            entity_terms,
            context_terms,
            window=window,
        )

    @staticmethod
    def _document_supports_candidate(
        document: NewsDocument,
        entity_terms: list[str],
        context_terms: list[str],
        relax_context_for_entity_match: bool = False,
    ) -> bool:
        return topic_discovery_candidates.document_supports_candidate(
            document,
            entity_terms,
            context_terms,
            relax_context_for_entity_match=relax_context_for_entity_match,
        )

    @staticmethod
    def _document_entity_metadata_match(
        document: NewsDocument, entity_terms: list[str]
    ) -> bool | None:
        return topic_discovery_candidates.document_entity_metadata_match(document, entity_terms)

    @staticmethod
    def _has_context_term(normalized_haystack: str, context_terms: list[str]) -> bool:
        return topic_discovery_candidates.has_context_term(normalized_haystack, context_terms)

    @staticmethod
    def _term_positions(haystack: str, terms: list[str]) -> list[int]:
        return topic_discovery_candidates.term_positions(haystack, terms)

    @staticmethod
    def _contains_entity_term(haystack: str, term: str) -> bool:
        return topic_discovery_candidates.contains_entity_term(haystack, term)

    @staticmethod
    def _looks_like_unrelated_release_document(document: NewsDocument) -> bool:
        return topic_discovery_candidates.looks_like_unrelated_release_document(document)

    @staticmethod
    def _evidence_source_count(documents: list[NewsDocument]) -> int:
        return topic_discovery_candidates.evidence_source_count(documents)

    @staticmethod
    def _candidate_evidence_sources(documents: list[NewsDocument], limit: int = 5) -> list[dict]:
        return topic_discovery_candidates.candidate_evidence_sources(documents, limit=limit)

    @staticmethod
    def _candidate_evidence_confidence(documents: list[NewsDocument], source_count: int) -> dict:
        return topic_discovery_candidates.candidate_evidence_confidence(documents, source_count)

    @staticmethod
    def _cap_confidence_by_source_credibility(score: int, credibility: dict) -> int:
        return topic_discovery_candidates.cap_confidence_by_source_credibility(score, credibility)

    @staticmethod
    def _source_credibility_label(weight: float) -> str:
        return topic_discovery_candidates.source_credibility_label(weight)

    @staticmethod
    def _recency_score(latest_date) -> int:
        return topic_discovery_candidates.recency_score_for_latest_date(latest_date)

    @staticmethod
    def _confidence_label(score: int) -> str:
        return topic_discovery_candidates.confidence_label(score)

    @staticmethod
    def _candidate_status(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        evidence_stale: bool = False,
    ) -> str:
        return topic_discovery_candidates.candidate_status(
            evidence_count,
            source_count,
            confidence_score=confidence_score,
            evidence_stale=evidence_stale,
        )

    @staticmethod
    def _candidate_validation_reason(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        latest_evidence_date: str | None = None,
        evidence_age_days: int | None = None,
        evidence_stale: bool = False,
    ) -> str:
        return topic_discovery_candidates.candidate_validation_reason(
            evidence_count,
            source_count,
            confidence_score=confidence_score,
            latest_evidence_date=latest_evidence_date,
            evidence_age_days=evidence_age_days,
            evidence_stale=evidence_stale,
        )

    @staticmethod
    def _candidate_next_action(
        evidence_count: int,
        source_count: int,
        confidence_score: int = 0,
        evidence_stale: bool = False,
    ) -> str:
        return topic_discovery_candidates.candidate_next_action(
            evidence_count,
            source_count,
            confidence_score=confidence_score,
            evidence_stale=evidence_stale,
        )

    @staticmethod
    def parse_plan(raw_text: str) -> TopicDiscoveryPlan:
        return topic_discovery_parser.parse_plan(raw_text)

    @staticmethod
    def enrich_plan(plan: TopicDiscoveryPlan, topic: str | None = None) -> TopicDiscoveryPlan:
        return topic_discovery_enrichment.enrich_plan(plan, topic=topic)

    @staticmethod
    def _ensure_upstream_material_layer(
        plan: TopicDiscoveryPlan, topic: str | None = None
    ) -> TopicDiscoveryPlan:
        return topic_discovery_enrichment.ensure_upstream_material_layer(plan, topic=topic)

    @staticmethod
    def _ai_upstream_material_subtopics() -> list[DiscoverySubtopic]:
        return topic_discovery_enrichment.ai_upstream_material_subtopics()

    @staticmethod
    def _robotics_upstream_material_subtopics() -> list[DiscoverySubtopic]:
        return topic_discovery_enrichment.robotics_upstream_material_subtopics()

    @staticmethod
    def _ai_upstream_material_candidates() -> list[CandidateCompany]:
        return topic_discovery_enrichment.ai_upstream_material_candidates()

    @staticmethod
    def _robotics_upstream_material_candidates() -> list[CandidateCompany]:
        return topic_discovery_enrichment.robotics_upstream_material_candidates()

    @staticmethod
    def infer_source_intents(subtopic: DiscoverySubtopic) -> list[str]:
        return topic_discovery_enrichment.infer_source_intents(subtopic)

    @staticmethod
    def _extract_json(raw_text: str) -> str:
        return topic_discovery_parser.extract_json(raw_text)

    @staticmethod
    def _prompt(topic: str) -> str:
        return topic_discovery_prompts.topic_discovery_prompt(topic)

    @staticmethod
    def _repair_prompt(topic: str, plan: TopicDiscoveryPlan, quality: DiscoveryPlanQuality) -> str:
        return topic_discovery_prompts.topic_discovery_repair_prompt(topic, plan, quality)
