from __future__ import annotations

from app.services import topic_discovery_candidate_queries, topic_discovery_news_queries
from app.services.topic_discovery_models import DiscoverySubtopic, TopicDiscoveryPlan


def supplemental_subtopics(
    plan: TopicDiscoveryPlan,
    missing_subtopics: list[str] | None = None,
) -> list[DiscoverySubtopic]:
    target_names = set(missing_subtopics or [])
    return [
        subtopic
        for subtopic in plan.subtopics
        if not target_names or (subtopic.name or "未命名子題") in target_names
    ]


def supplemental_subtopic_queries(
    plan: TopicDiscoveryPlan,
    missing_subtopics: list[str] | None = None,
) -> list[str]:
    queries: list[str] = []
    for subtopic in supplemental_subtopics(plan, missing_subtopics=missing_subtopics):
        evidence_terms = " ".join(subtopic.required_evidence[:2])
        risk_terms = " ".join(subtopic.risk_focus[:2])
        queries.append(f"{subtopic.name} {subtopic.rationale} {evidence_terms} 台股".strip())
        if risk_terms:
            queries.append(f"{subtopic.name} {risk_terms} 風險 瓶頸".strip())
        for query in subtopic.search_queries[:2]:
            queries.append(f"{query} 最新")
    return [query for query in queries if query]


def supplemental_subtopic_query_metadata(
    plan: TopicDiscoveryPlan,
    missing_subtopics: list[str] | None = None,
) -> list[dict]:
    return topic_discovery_news_queries.google_news_metadata_from_queries(
        supplemental_subtopic_queries(plan, missing_subtopics=missing_subtopics),
        source_type="supplemental",
        hypothesis=topic_discovery_candidate_queries.SUPPLEMENTAL_HYPOTHESIS,
        evidence_type="補抓資料源",
        source_intent="company_disclosure",
        max_urls=None,
        existing_urls=[],
    )
