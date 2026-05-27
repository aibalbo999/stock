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
    assert result["subtopic_readiness"]
    assert result["missing_subtopic_count"] >= 0
    assert result["sample"][0]["source_category"] == "cloud_capex"
    assert "international_context" in result["sample"][0]["source_intents"]
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
    assert result["missing_subtopic_count"] == len(plan.subtopics)


def test_source_relevance_reports_subtopic_readiness_by_research_task() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "液冷散熱",
              "objective": "確認液冷散熱是否形成出貨瓶頸",
              "required_evidence": ["液冷訂單", "產能"],
              "risk_focus": ["交期延遲"],
              "search_queries": ["AI 伺服器 液冷 產能"],
              "source_intents": ["industry_news", "capacity_supply"]
            },
            {
              "name": "出口管制",
              "objective": "查核政策限制",
              "required_evidence": ["出口管制"],
              "risk_focus": ["禁令"],
              "search_queries": ["export control AI chips Taiwan"]
            }
          ],
          "candidate_companies": []
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="AI 伺服器液冷散熱產能擴張",
            text="液冷散熱訂單增加，但產能與交期仍可能形成瓶頸。",
            publisher="科技新報",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="AI 伺服器液冷散熱供應鏈更新",
            text="液冷散熱供應鏈新增產能，出貨交期改善。",
            publisher="中央社科技",
            published_at=date(2026, 5, 21),
        ),
    ]

    result = SourceRelevanceAnalyzer().analyze(plan, documents)

    assert result["subtopic_readiness"]["液冷散熱"]["status"] == "ready"
    assert result["subtopic_readiness"]["出口管制"]["status"] == "missing"
    assert result["missing_subtopic_count"] == 1


def test_source_relevance_keeps_subtopic_weak_when_required_intent_is_missing() -> None:
    plan = TopicDiscoveryService.parse_plan(
        """
        {
          "subtopics": [
            {
              "name": "政策風險",
              "objective": "查核出口管制是否影響供應鏈",
              "required_evidence": ["出口管制"],
              "risk_focus": ["政策禁令"],
              "search_queries": ["export control AI chips Taiwan"],
              "source_intents": ["regulatory_policy"]
            }
          ],
          "candidate_companies": []
        }
        """
    )
    documents = [
        NewsFetcher.from_manual_text(
            title="政策風險與出口管制影響 AI 晶片",
            text="市場討論政策風險與出口管制，但未提供法規原始說明。",
            publisher="科技新報",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="AI 晶片供應鏈評估政策風險",
            text="供應鏈持續評估政策風險與出口限制。",
            publisher="中央社科技",
            published_at=date(2026, 5, 21),
        ),
    ]

    result = SourceRelevanceAnalyzer().analyze(plan, documents)

    readiness = result["subtopic_readiness"]["政策風險"]
    assert readiness["document_count"] == 2
    assert readiness["publisher_count"] == 2
    assert readiness["status"] == "weak"
    assert readiness["missing_source_intents"] == ["regulatory_policy"]
