from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from app.services.discovery_api import DiscoveryApiService


class FakeCandidate:
    def __init__(self, ticker: str, status: str = "evidence_supported") -> None:
        self.ticker = ticker
        self.status = status

    def model_dump(self):
        return {"ticker": self.ticker, "status": self.status}


def test_discovery_api_service_returns_topic_plan() -> None:
    class FakeDiscoveryService:
        def discover(self, topic: str):
            return {"topic": topic, "plan": {"subtopics": []}}

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DiscoveryApiService(
        session_scope_factory=fake_session_scope,
        topic_discovery_service_cls=FakeDiscoveryService,
    )

    assert service.topic_plan(SimpleNamespace(topic="AI 產業鏈")) == {
        "topic": "AI 產業鏈",
        "plan": {"subtopics": []},
    }


def test_discovery_api_service_ingests_discovery_with_injected_workflow() -> None:
    captured = {}

    class FakeDiscoveryService:
        pass

    class FakePlan:
        @classmethod
        def model_validate(cls, data):
            captured["plan_data"] = data
            return {"validated_plan": data}

    async def fake_discover(service, topic):
        captured["discover_service"] = service.__class__.__name__
        captured["topic"] = topic
        return {"plan": {"name": "plan"}, "quality": {"status": "ready"}}

    def fake_fetch_settings(payload):
        assert payload.topic == "AI 產業鏈"
        return 8, 80, 24

    def fake_document_limit(payload, evidence_limit):
        assert evidence_limit == 80
        return 320

    async def fake_run_ingestion(payload, service, plan, limit_per_query, evidence_limit, max_queries, document_limit):
        captured["run"] = {
            "plan": plan,
            "limit_per_query": limit_per_query,
            "evidence_limit": evidence_limit,
            "max_queries": max_queries,
            "document_limit": document_limit,
        }
        return {
            "urls": ["https://news.google.com/rss/search?q=AI"],
            "ingestion_results": [{"count": 1}],
            "fixed_source_ingestion": {"count": 2},
            "dynamic_query_ingestion": [{"count": 3}],
            "source_audit": {"total_stored_count": 6},
            "candidates": [FakeCandidate("2330")],
        }

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DiscoveryApiService(
        session_scope_factory=fake_session_scope,
        topic_discovery_service_cls=FakeDiscoveryService,
        topic_discovery_plan_cls=FakePlan,
        discover_topic_with_timeout_func=fake_discover,
        discovery_fetch_settings_func=fake_fetch_settings,
        discovery_document_limit_func=fake_document_limit,
        run_topic_discovery_ingestion_func=fake_run_ingestion,
    )

    result = asyncio.run(service.ingest(SimpleNamespace(topic="AI 產業鏈")))

    assert captured["discover_service"] == "FakeDiscoveryService"
    assert captured["plan_data"] == {"name": "plan"}
    assert captured["run"] == {
        "plan": {"validated_plan": {"name": "plan"}},
        "limit_per_query": 8,
        "evidence_limit": 80,
        "max_queries": 24,
        "document_limit": 320,
    }
    assert result["queries"] == ["https://news.google.com/rss/search?q=AI"]
    assert result["candidate_whitelist"] == [{"ticker": "2330", "status": "evidence_supported"}]
    assert result["source_audit"] == {"total_stored_count": 6}


def test_discovery_api_service_candidate_whitelist_filters_recent_quality_documents() -> None:
    captured = {}
    raw_documents = [SimpleNamespace(id="doc-old"), SimpleNamespace(id="doc-good")]

    class FakeDiscoveryService:
        def discover(self, topic: str):
            return {"topic": topic, "plan": {"name": "plan"}}

        def validate_candidates(self, plan, documents):
            captured["validate"] = {"plan": plan, "documents": documents}
            return [FakeCandidate("2330"), FakeCandidate("3324", "weak_evidence")]

        def evaluate_plan_quality(self, plan):
            return SimpleNamespace(model_dump=lambda: {"status": "ready"})

    class FakePlan:
        @classmethod
        def model_validate(cls, data):
            return {"validated_plan": data}

    class FakeNewsRepository:
        def __init__(self, session: object) -> None:
            captured["session"] = session

        def latest_documents(self, limit: int):
            captured["limit"] = limit
            return raw_documents

    class FakeIngestionPipeline:
        @staticmethod
        def _filter_documents(documents, start_date, end_date, quality_filter=True):
            captured["filter"] = {
                "documents": documents,
                "start_date": start_date,
                "end_date": end_date,
                "quality_filter": quality_filter,
            }
            return [documents[-1]]

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DiscoveryApiService(
        session_scope_factory=fake_session_scope,
        topic_discovery_service_cls=FakeDiscoveryService,
        topic_discovery_plan_cls=FakePlan,
        news_repository_cls=FakeNewsRepository,
        ingestion_pipeline_cls=FakeIngestionPipeline,
        today_func=lambda: date(2026, 6, 1),
    )

    result = service.candidate_whitelist(
        SimpleNamespace(topic="AI 產業鏈", lookback_days=30, evidence_limit=40)
    )

    assert captured["limit"] == 200
    assert captured["filter"] == {
        "documents": raw_documents,
        "start_date": date(2026, 5, 2),
        "end_date": date(2026, 6, 1),
        "quality_filter": True,
    }
    assert captured["validate"]["documents"] == [raw_documents[-1]]
    assert result["plan_quality"] == {"status": "ready"}
    assert result["candidate_whitelist"] == [
        {"ticker": "2330", "status": "evidence_supported"},
        {"ticker": "3324", "status": "weak_evidence"},
    ]
