from __future__ import annotations

from collections import Counter

from app.models.schemas import NewsDocument
from app.services.topic_discovery import TopicDiscoveryPlan, TopicDiscoveryService


class SourceRelevanceAnalyzer:
    def __init__(self, service: TopicDiscoveryService | None = None) -> None:
        self.service = service or TopicDiscoveryService()

    def analyze(self, plan: TopicDiscoveryPlan, documents: list[NewsDocument], limit: int = 80) -> dict:
        items = [self.document_relevance(plan, document) for document in documents[:limit]]
        relevant_items = [item for item in items if item["relevance_score"] > 0]
        subtopic_counter: Counter[str] = Counter()
        candidate_counter: Counter[str] = Counter()
        for item in relevant_items:
            subtopic_counter.update(item["subtopics"])
            candidate_counter.update(match["ticker"] for match in item["candidate_matches"])
        return {
            "analyzed_document_count": len(items),
            "relevant_document_count": len(relevant_items),
            "subtopic_coverage": dict(subtopic_counter),
            "candidate_coverage": dict(candidate_counter),
            "sample": relevant_items[:12],
        }

    def document_relevance(self, plan: TopicDiscoveryPlan, document: NewsDocument) -> dict:
        haystack = f"{document.title}\n{document.text}"
        subtopics = self._matched_subtopics(plan, haystack)
        candidate_matches = self._matched_candidates(plan, haystack)
        source_category = self._source_category(document)
        score = 0
        if subtopics or candidate_matches:
            score = min(
                100,
                len(subtopics) * 18
                + len(candidate_matches) * 22
                + self._source_category_score(source_category)
                + self._freshness_score(document),
            )
        reasons = []
        if subtopics:
            reasons.append("對應研究子題：" + "、".join(subtopics[:3]))
        if candidate_matches:
            reasons.append("對應候選公司：" + "、".join(match["label"] for match in candidate_matches[:3]))
        if source_category != "news":
            reasons.append(f"來源類別：{source_category}")
        return {
            "document_id": document.id,
            "title": document.title,
            "publisher": document.source.publisher,
            "published_at": document.source.published_at.isoformat() if document.source.published_at else None,
            "source_category": source_category,
            "relevance_score": score,
            "subtopics": subtopics,
            "candidate_matches": candidate_matches,
            "reasons": reasons,
        }

    def _matched_subtopics(self, plan: TopicDiscoveryPlan, haystack: str) -> list[str]:
        lowered = haystack.lower()
        matches = []
        for subtopic in plan.subtopics:
            terms = self.service._research_terms(subtopic)
            hit_count = sum(1 for term in terms if term.lower() in lowered)
            if hit_count >= 2 or (subtopic.name and subtopic.name.lower() in lowered):
                matches.append(subtopic.name or "未命名子題")
        return matches

    def _matched_candidates(self, plan: TopicDiscoveryPlan, haystack: str) -> list[dict]:
        matches = []
        for candidate in plan.candidate_companies:
            if not self.service._has_entity_and_context(
                haystack,
                self.service._candidate_entity_terms(candidate),
                self.service._candidate_context_terms(candidate, plan),
            ):
                continue
            matches.append(
                {
                    "ticker": candidate.ticker,
                    "name": candidate.name,
                    "segment": candidate.segment,
                    "label": f"{candidate.ticker} {candidate.name}",
                }
            )
        return matches

    @staticmethod
    def _source_category(document: NewsDocument) -> str:
        publisher = (document.source.publisher or "").lower()
        url = (document.source.url or "").lower()
        haystack = f"{publisher} {url}"
        if "nvidia" in haystack:
            return "ai_chip_vendor"
        if any(term in haystack for term in ["aws", "google", "meta", "openai"]):
            return "cloud_capex"
        if any(term in haystack for term in ["datacenter", "opencompute", "open-compute", "dcd"]):
            return "datacenter_power"
        if "semiengineering" in haystack or "semiconductor engineering" in haystack:
            return "semiconductor_industry"
        if "news.google.com" in haystack:
            return "dynamic_search"
        return "news"

    @staticmethod
    def _source_category_score(category: str) -> int:
        return {
            "ai_chip_vendor": 14,
            "cloud_capex": 12,
            "datacenter_power": 10,
            "semiconductor_industry": 10,
            "dynamic_search": 6,
        }.get(category, 2)

    @staticmethod
    def _freshness_score(document: NewsDocument) -> int:
        return 6 if document.source.published_at else 0
