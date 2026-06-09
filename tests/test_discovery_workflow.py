import asyncio
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.models.schemas import NewsDocument, Source
from app.services import discovery_workflow, discovery_workflow_audit, discovery_workflow_settings
from app.services.discovery_workflow import (
    DiscoveryWorkflowService,
    build_source_audit,
    discovery_fetch_settings,
    discovery_query_budget,
)


def test_discovery_source_audit_helpers_live_outside_workflow_service() -> None:
    workflow_source = Path("app/services/discovery_workflow.py").read_text()
    audit_source = Path("app/services/discovery_workflow_audit.py").read_text()

    assert discovery_workflow.build_source_audit is discovery_workflow_audit.build_source_audit
    assert (
        discovery_workflow.summarize_ingestion_stage
        is discovery_workflow_audit.summarize_ingestion_stage
    )
    assert discovery_workflow.query_type_label is discovery_workflow_audit.query_type_label
    assert discovery_workflow.query_intent_label is discovery_workflow_audit.query_intent_label
    for helper in [
        "def summarize_ingestion_stage(",
        "def summarize_source_categories(",
        "def summarize_source_intents(",
        "def summarize_source_selection(",
        "def build_source_audit(",
        "def query_type_label(",
        "def query_intent_label(",
    ]:
        assert helper not in workflow_source
        assert helper in audit_source


def test_discovery_settings_helpers_live_outside_workflow_service() -> None:
    workflow_source = Path("app/services/discovery_workflow.py").read_text()
    settings_source = Path("app/services/discovery_workflow_settings.py").read_text()

    assert (
        discovery_workflow.discovery_analysis_mode
        is discovery_workflow_settings.discovery_analysis_mode
    )
    assert (
        discovery_workflow.discovery_fetch_settings
        is discovery_workflow_settings.discovery_fetch_settings
    )
    assert (
        discovery_workflow.discovery_effective_lookback_days
        is discovery_workflow_settings.discovery_effective_lookback_days
    )
    for helper in [
        "def discovery_analysis_mode(",
        "def is_deep_discovery(",
        "def discovery_fetch_settings(",
        "def discovery_effective_lookback_days(",
        "def discovery_document_limit(",
        "def discovery_market_history_days(",
        "def discovery_valuation_history_days(",
    ]:
        assert helper not in workflow_source
        assert helper in settings_source


def test_discovery_workflow_source_audit_lives_in_service_layer() -> None:
    payload = SimpleNamespace(
        topic="AI 產業鏈",
        lookback_days=21,
        deep_analysis=True,
        analysis_mode="standard",
        include_international=True,
        limit_per_query=5,
        evidence_limit=40,
    )

    limit_per_query, evidence_limit, max_queries = discovery_fetch_settings(payload)
    audit = build_source_audit(
        payload=payload,
        urls=["https://news.google.com/rss/search?q=CoWoS"],
        fixed_source_ingestion={
            "count": 2,
            "items": [{"title": "固定來源"}],
            "errors": [],
            "source_category_counts": {"taiwan_news": 2},
            "source_results": [{"source_intents": ["industry_news"], "stored_count": 2}],
        },
        dynamic_query_ingestion=[
            {
                "count": 1,
                "items": [{"title": "動態來源"}],
                "errors": [],
                "source_category_counts": {"semiconductor_industry": 1},
            }
        ],
        limit_per_query=limit_per_query,
        evidence_limit=evidence_limit,
        max_queries=max_queries,
        query_metadata=[
            {
                "query": "CoWoS",
                "source_type": "subtopic",
                "source_intent": "capacity_supply",
            }
        ],
    )
    budget = discovery_query_budget(max_queries, deep_analysis=True)

    assert audit["analysis_mode"] == "deep"
    assert audit["effective_lookback_days"] == 120
    assert audit["total_stored_count"] == 3
    assert audit["query_type_labels"]["subtopic"]["label"] == "子題查詢"
    assert audit["query_intent_labels"]["capacity_supply"]["label"] == "產能供給"
    assert budget["supplemental_rounds"] == 4


def test_discovery_workflow_ingests_dynamic_news_with_injected_dependencies() -> None:
    captured = {"upserted": [], "stored": []}
    document = NewsDocument(
        id="doc-1",
        title="台積電 CoWoS 產能",
        text="台積電 CoWoS 先進封裝產能擴張。",
        source=Source(
            title="台積電 CoWoS 產能",
            publisher="測試來源",
            published_at=date(2026, 5, 1),
        ),
    )

    class FakeFetcher:
        async def fetch_feed(self, url: str, publisher=None, limit: int = 10):
            assert url == "https://news.google.com/rss/search?q=CoWoS"
            assert limit == 12
            return [document]

    class FakeIngestionPipeline:
        @staticmethod
        def _filter_documents(documents, start_date, end_date, quality_filter=True):
            return documents

        @staticmethod
        def _dedupe_documents(documents):
            deduped = {}
            for item in documents:
                deduped.setdefault(item.id, item)
            return list(deduped.values())

    class FakeMatch:
        def model_dump(self, mode=None):
            return {"ticker": "2330", "name": "台積電"}

    class FakeMapper:
        def match_document(self, item):
            assert item.id == "doc-1"
            return [FakeMatch()]

    class FakeVectorStore:
        def upsert_documents(self, documents):
            captured["upserted"] = [item.id for item in documents]

    class FakeNewsRepository:
        def __init__(self, session):
            self.session = session

        def upsert_document(self, item, matches):
            captured["stored"].append((item.id, matches))

    @contextmanager
    def fake_session_scope():
        yield object()

    service = DiscoveryWorkflowService(
        session_scope_factory=fake_session_scope,
        ingestion_pipeline_cls=FakeIngestionPipeline,
        news_repository_cls=FakeNewsRepository,
        news_fetcher_cls=FakeFetcher,
        entity_mapper_cls=FakeMapper,
        vector_store_cls=FakeVectorStore,
    )

    result = asyncio.run(
        service.ingest_dynamic_news_urls(
            ["https://news.google.com/rss/search?q=CoWoS"],
            limit_per_query=2,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 5, 31),
        )
    )

    assert result[0]["count"] == 1
    assert result[0]["items"][0]["entity_matches"] == [{"ticker": "2330", "name": "台積電"}]
    assert captured["upserted"] == ["doc-1"]
    assert captured["stored"] == [("doc-1", [{"ticker": "2330", "name": "台積電"}])]
