from datetime import timedelta

from app.api.schemas import TopicDiscoveryRequest
from app.core.time import now_taipei
from app.models.schemas import NewsDocument, Source
from app.services.discovered_pipeline import (
    candidate_filing_revalidation_tickers,
    should_revalidate_candidate_filings,
)
from app.services.discovery_workflow import (
    build_source_audit,
    discovery_document_limit,
    discovery_effective_lookback_days,
    discovery_fetch_settings,
    discovery_market_history_days,
    discovery_query_budget,
    discovery_valuation_history_days,
    escalate_discovery_budget,
    should_escalate_discovery_budget,
    should_supplement_discovery_sources,
)
from app.services.report_quality import summarize_document_source_quality


def test_source_audit_summarizes_fixed_and_dynamic_ingestion() -> None:
    payload = TopicDiscoveryRequest(
        topic="AI 產業鏈",
        lookback_days=21,
        deep_analysis=True,
        include_international=True,
    )

    audit = build_source_audit(
        payload=payload,
        urls=["https://news.google.com/search?q=AI", "https://news.google.com/search?q=HBM"],
        fixed_source_ingestion={
            "count": 2,
            "items": [{"title": "固定來源 A"}, {"title": "固定來源 B"}],
            "errors": [],
            "source_category_counts": {"taiwan_news": 2},
            "source_results": [
                {
                    "category": "taiwan_news",
                    "source_intents": ["industry_news"],
                    "stored_count": 2,
                }
            ],
            "source_selection": {
                "selected": [{"name": "technews", "match_score": 1}],
                "skipped": [{"name": "nvidia-newsroom", "reason": "topic_not_matched"}],
            },
        },
        dynamic_query_ingestion=[
            {
                "count": 3,
                "items": [{"title": "動態來源 A"}, {"title": "動態來源 B"}],
                "errors": [{"source": "bad", "error": "timeout"}],
                "source_category_counts": {"cloud_capex": 3},
            },
            {
                "count": 1,
                "items": [{"title": "動態來源 C"}],
                "errors": [],
                "source_category_counts": {"semiconductor_industry": 1},
            },
        ],
        limit_per_query=12,
        evidence_limit=120,
        max_queries=80,
        query_metadata=[
            {
                "url": "https://news.google.com/search?q=AI",
                "query": "AI",
                "source_type": "subtopic",
                "hypothesis": "驗證 AI 需求",
                "evidence_type": "需求/成長",
                "source_intent": "industry_news",
                "language": "en",
            },
            {
                "url": "https://news.google.com/search?q=HBM",
                "query": "HBM",
                "source_type": "coverage_gap",
                "hypothesis": "補齊 HBM 缺口",
                "evidence_type": "品質缺口補強",
                "source_intent": "capacity_supply",
                "language": "en",
            },
        ],
    )

    assert audit["topic"] == "AI 產業鏈"
    assert audit["lookback_days"] == 21
    assert audit["effective_lookback_days"] == 120
    assert audit["analysis_mode"] == "deep"
    assert audit["deep_analysis"] is True
    assert audit["include_international"] is True
    assert audit["fixed_sources"]["stored_count"] == 2
    assert audit["fixed_sources"]["source_category_counts"] == {"taiwan_news": 2}
    assert audit["fixed_sources"]["source_intent_counts"] == {"industry_news": 2}
    assert audit["fixed_sources"]["source_selection"]["selected_count"] == 1
    assert audit["fixed_sources"]["source_selection"]["skipped_count"] == 1
    assert audit["dynamic_queries"]["stored_count"] == 4
    assert audit["dynamic_queries"]["source_category_counts"] == {
        "cloud_capex": 3,
        "semiconductor_industry": 1,
    }
    assert audit["dynamic_query_count"] == 2
    assert audit["total_stored_count"] == 6
    assert audit["total_error_count"] == 1
    assert audit["dynamic_query_sample"] == [
        "https://news.google.com/search?q=AI",
        "https://news.google.com/search?q=HBM",
    ]
    assert audit["query_type_counts"] == {"subtopic": 1, "coverage_gap": 1}
    assert audit["query_intent_counts"] == {"industry_news": 1, "capacity_supply": 1}
    assert audit["query_intent_labels"]["capacity_supply"]["label"] == "產能供給"
    assert audit["query_type_labels"]["subtopic"]["label"] == "子題查詢"
    assert audit["query_type_labels"]["coverage_gap"]["label"] == "缺口補強查詢"
    assert audit["query_metadata_sample"][1]["source_type"] == "coverage_gap"
    assert audit["query_metadata_sample"][0]["hypothesis"] == "驗證 AI 需求"
    assert audit["query_metadata_sample"][1]["evidence_type"] == "品質缺口補強"


def test_deep_discovery_fetch_settings_raise_source_and_evidence_limits() -> None:
    payload = TopicDiscoveryRequest(
        topic="AI 產業鏈",
        limit_per_query=5,
        evidence_limit=40,
        deep_analysis=True,
    )

    assert discovery_fetch_settings(payload) == (20, 180, 72)
    assert discovery_effective_lookback_days(payload) == 120
    assert discovery_document_limit(payload, 180) == 1000
    assert discovery_market_history_days(payload) == 720
    assert discovery_valuation_history_days(payload) == 180


def test_standard_discovery_fetch_settings_are_deeper_than_fast_preview() -> None:
    fast = TopicDiscoveryRequest(topic="AI 產業鏈", analysis_mode="fast")
    standard = TopicDiscoveryRequest(topic="AI 產業鏈", analysis_mode="standard")

    assert discovery_fetch_settings(fast) == (8, 80, 24)
    assert discovery_fetch_settings(standard) == (8, 80, 36)
    assert discovery_effective_lookback_days(standard) == 60
    assert discovery_document_limit(standard, 80) == 600


def test_discovery_query_budget_reserves_supplemental_capacity() -> None:
    normal_budget = discovery_query_budget(36, analysis_mode="standard")
    deep_budget = discovery_query_budget(80, deep_analysis=True)

    assert normal_budget["initial_queries"] < 36
    assert normal_budget["supplemental_queries"] > 0
    assert normal_budget["supplemental_rounds"] == 3
    assert deep_budget["initial_queries"] < 80
    assert deep_budget["supplemental_queries"] > normal_budget["supplemental_queries"]
    assert deep_budget["supplemental_rounds"] == 4
    assert deep_budget["supplemental_batch_size"] == 12
    assert deep_budget["no_gain_stop_rounds"] == 2


def test_discovery_budget_auto_escalates_on_source_coverage_gaps() -> None:
    budget = discovery_query_budget(36, analysis_mode="standard")
    source_audit = {
        "plan_quality": {"status": "ready"},
        "source_relevance": {"missing_subtopic_count": 2, "weak_subtopic_count": 0},
    }
    candidate_support = {"total": 5, "supported_ratio": 0.8}

    assert should_escalate_discovery_budget(source_audit, candidate_support, budget) is True
    escalated = escalate_discovery_budget(budget, 36)
    assert escalated["escalated"] is True
    assert escalated["supplemental_rounds"] == 5
    assert escalated["supplemental_batch_size"] == 12


def test_discovery_budget_does_not_escalate_deep_mode() -> None:
    budget = discovery_query_budget(72, analysis_mode="deep")
    source_audit = {
        "plan_quality": {"status": "insufficient"},
        "source_relevance": {"missing_subtopic_count": 3},
    }

    assert should_escalate_discovery_budget(source_audit, {"total": 0}, budget) is False


def test_candidate_filing_revalidation_triggers_when_supported_ratio_is_low() -> None:
    candidates = [
        {"ticker": "2330", "status": "evidence_supported"},
        {"ticker": "2382", "status": "weak_evidence"},
        {"ticker": "3231", "status": "needs_evidence"},
    ]

    assert should_revalidate_candidate_filings(candidates) is True
    assert should_revalidate_candidate_filings([{"ticker": "2330", "status": "evidence_supported"}]) is False


def test_candidate_filing_revalidation_prioritizes_unpromoted_candidates() -> None:
    candidates = [
        {"ticker": "2330", "status": "evidence_supported"},
        {"ticker": "2382", "status": "weak_evidence"},
        {"ticker": "3231", "status": "needs_evidence"},
        {"ticker": "3324", "status": "weak_evidence"},
    ]
    payload = TopicDiscoveryRequest(topic="AI 產業鏈", deep_analysis=True)

    assert candidate_filing_revalidation_tickers(candidates, payload)[:3] == ["2382", "3231", "3324"]
    assert "2330" in candidate_filing_revalidation_tickers(candidates, payload)


def test_source_audit_marks_low_candidate_coverage_for_supplement() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 30},
    }
    candidate_support = {
        "total": 5,
        "supported": 2,
        "unsupported": 3,
        "supported_ratio": 0.4,
    }

    assert should_supplement_discovery_sources(audit, candidate_support) is True


def test_source_audit_supplements_when_multiple_candidates_still_have_gaps() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 40},
        "analysis_mode": "standard",
    }
    candidate_support = {
        "total": 10,
        "supported": 8,
        "weak": 1,
        "unsupported": 1,
        "supported_ratio": 0.8,
    }

    assert should_supplement_discovery_sources(audit, candidate_support) is True


def test_deep_source_audit_requires_higher_candidate_coverage() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 40},
        "analysis_mode": "deep",
    }
    candidate_support = {
        "total": 10,
        "supported": 7,
        "weak": 1,
        "unsupported": 0,
        "supported_ratio": 0.7,
    }

    assert should_supplement_discovery_sources(audit, candidate_support) is True


def test_source_audit_supplements_when_plan_query_quality_is_not_ready() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 30},
        "plan_quality": {
            "status": "caution",
            "query_quality": {
                "total_queries": 2,
                "generic_query_count": 1,
            },
        },
    }
    candidate_support = {
        "total": 5,
        "supported": 5,
        "unsupported": 0,
        "supported_ratio": 1,
    }

    assert should_supplement_discovery_sources(audit, candidate_support) is True


def test_source_audit_supplements_when_subtopic_has_no_relevant_sources() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 30},
        "source_relevance": {"missing_subtopic_count": 1},
    }
    candidate_support = {
        "total": 5,
        "supported": 5,
        "unsupported": 0,
        "supported_ratio": 1,
    }

    assert should_supplement_discovery_sources(audit, candidate_support) is True


def test_source_audit_accepts_sufficient_candidate_and_source_coverage() -> None:
    audit = {
        "dynamic_queries": {"stored_count": 18},
    }
    candidate_support = {
        "total": 5,
        "supported": 4,
        "unsupported": 1,
        "supported_ratio": 0.8,
    }

    assert should_supplement_discovery_sources(audit, candidate_support) is False


def test_summarize_document_source_quality_measures_diversity_and_recency() -> None:
    recent = now_taipei().date() - timedelta(days=2)
    old = now_taipei().date() - timedelta(days=45)
    documents = [
        NewsDocument(
            id="doc-1",
            title="近期 A",
            text="測試",
            source=Source(title="近期 A", publisher="Source A", published_at=recent),
        ),
        NewsDocument(
            id="doc-2",
            title="近期 B",
            text="測試",
            source=Source(title="近期 B", publisher="Source B", published_at=recent),
        ),
        NewsDocument(
            id="doc-3",
            title="舊資料",
            text="測試",
            source=Source(title="舊資料", publisher="Source A", published_at=old),
        ),
        NewsDocument(
            id="doc-4",
            title="無日期",
            text="測試",
            source=Source(title="無日期", publisher="Source C"),
        ),
    ]

    quality = summarize_document_source_quality(documents, lookback_days=14)

    assert quality["total_documents"] == 4
    assert quality["unique_publisher_count"] == 3
    assert quality["timestamped_count"] == 3
    assert quality["timestamp_coverage"] == 0.75
    assert quality["recent_count"] == 2
    assert quality["recent_coverage"] == 0.5
    assert quality["high_credibility_count"] == 0
    assert quality["low_credibility_count"] == 0


def test_summarize_document_source_quality_measures_source_credibility() -> None:
    recent = now_taipei().date() - timedelta(days=2)
    documents = [
        NewsDocument(
            id="official",
            title="台積電股東會年報",
            text="公開資訊觀測站年報。",
            source=Source(title="台積電股東會年報", publisher="公開資訊觀測站 MOPS", published_at=recent),
        ),
        NewsDocument(
            id="news",
            title="台積電月營收創同期高",
            text="台積電月營收年增。",
            source=Source(title="台積電月營收創同期高", publisher="經濟日報", published_at=recent),
        ),
        NewsDocument(
            id="blog",
            title="台積電還能追嗎",
            text="投資網誌評論。",
            source=Source(title="台積電還能追嗎", publisher="CMoney投資網誌", published_at=recent),
        ),
    ]

    quality = summarize_document_source_quality(documents, lookback_days=14)

    assert quality["high_credibility_count"] == 2
    assert quality["low_credibility_count"] == 1
    assert quality["credibility_tier_counts"]["official"] == 1
    assert quality["credibility_tier_counts"]["investment_blog"] == 1
