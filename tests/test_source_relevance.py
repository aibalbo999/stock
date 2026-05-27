from datetime import date

from app.data_sources.news import NewsFetcher
from app.services.source_relevance import SourceRelevanceAnalyzer
from app.services.topic_discovery import TopicDiscoveryService


def test_source_relevance_links_documents_to_subtopics_and_candidates() -> None:
    plan = TopicDiscoveryService._fallback_plan("AI 產業鏈")
    document = NewsFetcher.from_manual_text(
        title="廣達 AI 伺服器出貨受雲端 capex 帶動",
        text="廣達 AI 伺服器出貨成長，雲端 CSP capex 支撐資料中心需求。",
        publisher="AWS News Blog",
        published_at=date(2026, 5, 20),
        url="https://aws.amazon.com/blogs/aws/example",
    )

    result = SourceRelevanceAnalyzer().analyze(plan, [document])

    assert result["analyzed_document_count"] == 1
    assert result["relevant_document_count"] == 1
    assert result["candidate_coverage"]["2382"] == 1
    assert result["sample"][0]["source_category"] == "cloud_capex"
    assert result["sample"][0]["candidate_matches"][0]["ticker"] == "2382"
    assert result["sample"][0]["relevance_score"] > 0


def test_source_relevance_ignores_unrelated_documents() -> None:
    plan = TopicDiscoveryService._fallback_plan("AI 產業鏈")
    document = NewsFetcher.from_manual_text(
        title=" unrelated consumer app update",
        text="This article is about a consumer app and does not mention infrastructure.",
        publisher="Example",
        published_at=date(2026, 5, 20),
    )

    result = SourceRelevanceAnalyzer().analyze(plan, [document])

    assert result["relevant_document_count"] == 0
    assert result["subtopic_coverage"] == {}
    assert result["candidate_coverage"] == {}
