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
        subtopic_readiness = self._empty_subtopic_readiness(plan)
        for item in relevant_items:
            subtopic_counter.update(item["subtopics"])
            candidate_counter.update(match["ticker"] for match in item["candidate_matches"])
            for subtopic_name in item["subtopics"]:
                readiness = subtopic_readiness.get(subtopic_name)
                if readiness is None:
                    continue
                readiness["document_count"] += 1
                if item["publisher"]:
                    readiness["publishers"].add(item["publisher"])
                readiness["source_categories"].update([item["source_category"]])
                readiness["covered_source_intents"].update(item["source_intents"])
        finalized_readiness = {
            name: self._finalize_subtopic_readiness(readiness)
            for name, readiness in subtopic_readiness.items()
        }
        return {
            "analyzed_document_count": len(items),
            "relevant_document_count": len(relevant_items),
            "subtopic_coverage": dict(subtopic_counter),
            "candidate_coverage": dict(candidate_counter),
            "subtopic_readiness": finalized_readiness,
            "missing_subtopic_count": sum(
                1 for readiness in finalized_readiness.values() if readiness["status"] == "missing"
            ),
            "weak_subtopic_count": sum(
                1 for readiness in finalized_readiness.values() if readiness["status"] == "weak"
            ),
            "sample": relevant_items[:12],
        }

    def document_relevance(self, plan: TopicDiscoveryPlan, document: NewsDocument) -> dict:
        haystack = f"{document.title}\n{document.text}"
        subtopics = self._matched_subtopics(plan, haystack)
        candidate_matches = self._matched_candidates(plan, haystack)
        source_category = self._source_category(document)
        source_intents = self._source_intents(source_category, document)
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
        if source_intents:
            reasons.append("來源意圖：" + "、".join(source_intents[:3]))
        return {
            "document_id": document.id,
            "title": document.title,
            "publisher": document.source.publisher,
            "published_at": document.source.published_at.isoformat() if document.source.published_at else None,
            "source_category": source_category,
            "source_intents": source_intents,
            "relevance_score": score,
            "subtopics": subtopics,
            "candidate_matches": candidate_matches,
            "reasons": reasons,
        }

    def _empty_subtopic_readiness(self, plan: TopicDiscoveryPlan) -> dict:
        return {
            subtopic.name or "未命名子題": {
                "required_source_intents": self._text_source_intents(subtopic.source_intents),
                "document_count": 0,
                "publishers": set(),
                "source_categories": Counter(),
                "covered_source_intents": set(),
            }
            for subtopic in plan.subtopics
        }

    @staticmethod
    def _finalize_subtopic_readiness(readiness: dict) -> dict:
        publisher_count = len(readiness["publishers"])
        document_count = int(readiness["document_count"])
        missing_intents = [
            intent
            for intent in readiness["required_source_intents"]
            if intent not in readiness["covered_source_intents"]
        ]
        if document_count == 0:
            status = "missing"
        elif document_count >= 2 and publisher_count >= 2:
            status = "ready"
        else:
            status = "weak"
        return {
            "status": status,
            "document_count": document_count,
            "publisher_count": publisher_count,
            "source_categories": dict(readiness["source_categories"]),
            "required_source_intents": readiness["required_source_intents"],
            "covered_source_intents": sorted(readiness["covered_source_intents"]),
            "missing_source_intents": missing_intents,
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
    def _source_intents(category: str, document: NewsDocument) -> list[str]:
        mapping = {
            "ai_chip_vendor": ["industry_news", "capacity_supply", "international_context"],
            "cloud_capex": ["industry_news", "international_context"],
            "datacenter_power": ["capacity_supply", "regulatory_policy", "international_context"],
            "semiconductor_industry": ["industry_news", "capacity_supply", "international_context"],
            "dynamic_search": ["industry_news"],
            "news": ["industry_news"],
        }
        intents = list(mapping.get(category, ["industry_news"]))
        text = f"{document.title}\n{document.text}".lower()
        if any(term in text for term in ["法說", "年報", "公開說明書", "重大訊息", "investor presentation"]):
            intents.append("company_disclosure")
        if any(term in text for term in ["出口管制", "禁令", "政策", "regulation", "export control"]):
            intents.append("regulatory_policy")
        return list(dict.fromkeys(intents))

    @staticmethod
    def _text_source_intents(intents: list[str]) -> list[str]:
        text_intents = {
            "industry_news",
            "company_disclosure",
            "capacity_supply",
            "regulatory_policy",
            "international_context",
        }
        return [intent for intent in intents if intent in text_intents]

    @staticmethod
    def _freshness_score(document: NewsDocument) -> int:
        return 6 if document.source.published_at else 0
