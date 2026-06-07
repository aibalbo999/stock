from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

from app.services.data_operations_api import DataOperationsApiService


def test_data_operations_service_lists_news_and_market_snapshots() -> None:
    captured = {}
    news_document = SimpleNamespace(
        id="news-1",
        title="台積電 CoWoS 擴產",
        source=SimpleNamespace(
            publisher="工商時報",
            published_at=date(2026, 5, 1),
            url="https://example.com/news-1",
        ),
    )
    snapshot = SimpleNamespace(model_dump=lambda mode="json": {"ticker": "2330", "close": 1000})

    class FakeNewsRepository:
        def __init__(self, session: object) -> None:
            captured["news_session"] = session

        def latest_documents(self, limit: int):
            captured["news_limit"] = limit
            return [news_document]

    class FakeMarketRepository:
        def __init__(self, session: object) -> None:
            captured["market_session"] = session

        def latest_by_tickers(self, tickers):
            captured["market_tickers"] = tickers
            return [snapshot]

    class FakeWhitelist:
        def allowed_tickers(self):
            return {"2330", "2382"}

    class FakeEntityMapper:
        whitelist = FakeWhitelist()

        def filter_allowed_tickers(self, tickers):
            captured["requested_tickers"] = tickers
            return [ticker for ticker in tickers if ticker == "2330"]

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DataOperationsApiService(
        session_scope_factory=fake_session_scope,
        news_repository_cls=FakeNewsRepository,
        market_repository_cls=FakeMarketRepository,
        entity_mapper_cls=FakeEntityMapper,
    )

    assert service.list_news(5) == [
        {
            "id": "news-1",
            "title": "台積電 CoWoS 擴產",
            "publisher": "工商時報",
            "published_at": "2026-05-01",
            "url": "https://example.com/news-1",
        }
    ]
    assert service.market_snapshots("2330,9999") == [{"ticker": "2330", "close": 1000}]
    assert captured == {
        "news_session": "session",
        "news_limit": 5,
        "requested_tickers": ["2330", "9999"],
        "market_session": "session",
        "market_tickers": ["2330"],
    }


def test_data_operations_service_returns_market_cache_summary() -> None:
    captured = {}
    snapshot = SimpleNamespace(model_dump=lambda mode="json": {"ticker": "2330", "close": 1000})
    valuation = SimpleNamespace(model_dump=lambda mode="json": {"ticker": "2330", "pe_ratio": 20.5})
    filing = SimpleNamespace(
        id="filing-1",
        ticker="2330",
        company_name="台積電",
        document_type="annual_report",
        title="年報",
        source=SimpleNamespace(
            publisher="MOPS",
            published_at=date(2026, 5, 1),
            url="https://example.com/filing",
        ),
    )

    class FakeMarketRepository:
        def __init__(self, session: object) -> None:
            captured["market_session"] = session

        def latest_by_tickers(self, tickers):
            captured["market_tickers"] = tickers
            return [snapshot]

    class FakeValuationRepository:
        def __init__(self, session: object) -> None:
            captured["valuation_session"] = session

        def latest_by_tickers(self, tickers):
            captured["valuation_tickers"] = tickers
            return [valuation]

    class FakeCompanyFilingRepository:
        def __init__(self, session: object) -> None:
            captured["filing_session"] = session

        def latest_by_tickers(self, tickers, limit_per_ticker=2):
            captured["filing_args"] = (tickers, limit_per_ticker)
            return [filing]

    class FakeFinancialMetricRepository:
        def __init__(self, session: object) -> None:
            captured["financial_session"] = session

        def by_tickers(self, tickers):
            captured["financial_tickers"] = tickers
            return [object(), object()]

    class FakeWhitelist:
        def allowed_tickers(self):
            return {"2330", "2382"}

    class FakeEntityMapper:
        whitelist = FakeWhitelist()

        def filter_allowed_tickers(self, tickers):
            return [ticker for ticker in tickers if ticker == "2330"]

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DataOperationsApiService(
        session_scope_factory=fake_session_scope,
        market_repository_cls=FakeMarketRepository,
        valuation_metric_repository_cls=FakeValuationRepository,
        company_filing_repository_cls=FakeCompanyFilingRepository,
        financial_metric_repository_cls=FakeFinancialMetricRepository,
        entity_mapper_cls=FakeEntityMapper,
    )

    summary = service.market_cache_summary("2330,9999", limit_per_ticker=3)

    assert summary["tickers"] == ["2330"]
    assert summary["market_snapshots"] == [{"ticker": "2330", "close": 1000}]
    assert summary["valuations"] == [{"ticker": "2330", "pe_ratio": 20.5}]
    assert summary["company_filings"][0]["publisher"] == "MOPS"
    assert summary["financial_metric_count"] == 2
    assert captured["filing_args"] == (["2330"], 3)


def test_data_operations_service_ingests_manual_news_to_rag_and_repository() -> None:
    captured = {}

    class FakeVectorStore:
        def upsert_documents(self, documents):
            captured["rag_document_id"] = documents[0].id

    class FakeMatch:
        def model_dump(self, mode="json"):
            return {"ticker": "2330", "name": "台積電"}

    class FakeEntityMapper:
        def match_document(self, document):
            captured["matched_title"] = document.title
            return [FakeMatch()]

    class FakeNewsRepository:
        def __init__(self, session: object) -> None:
            captured["session"] = session

        def upsert_document(self, document, matches):
            captured["stored"] = {
                "document_id": document.id,
                "matches": matches,
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DataOperationsApiService(
        session_scope_factory=fake_session_scope,
        news_repository_cls=FakeNewsRepository,
        vector_store_cls=FakeVectorStore,
        entity_mapper_cls=FakeEntityMapper,
    )

    result = service.ingest_manual_news(
        title="台積電 CoWoS 擴產",
        text="台積電 CoWoS 需求強勁。" * 8,
        publisher="manual",
        published_at=date(2026, 5, 1),
        url="https://example.com/tsmc",
    )

    assert result["document_id"] == captured["rag_document_id"]
    assert result["entity_matches"] == [{"ticker": "2330", "name": "台積電"}]
    assert captured["matched_title"] == "台積電 CoWoS 擴產"
    assert captured["stored"] == {
        "document_id": result["document_id"],
        "matches": [{"ticker": "2330", "name": "台積電"}],
    }


def test_data_operations_service_refreshes_market_with_default_windows() -> None:
    calls = []

    class FakePipeline:
        async def refresh_market(self, tickers, start_date, end_date):
            calls.append(("market", tickers, start_date, end_date))
            return {"stored_count": 2}

        async def refresh_financial_metrics(self, tickers, start_date, end_date):
            calls.append(("financial", tickers, start_date, end_date))
            return {"stored_count": 3}

        async def refresh_valuations(self, tickers, start_date, end_date):
            calls.append(("valuation", tickers, start_date, end_date))
            return {"stored_count": 4}

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DataOperationsApiService(
        session_scope_factory=fake_session_scope,
        ingestion_pipeline_cls=FakePipeline,
        today_func=lambda: date(2026, 6, 1),
    )

    market = asyncio.run(service.refresh_market(tickers=["2330"]))
    fundamentals = asyncio.run(service.refresh_fundamentals(tickers=["2330"]))

    assert market == {"stored_count": 2}
    assert fundamentals == {
        "financial_metrics": {"stored_count": 3},
        "valuations": {"stored_count": 4},
    }
    assert calls == [
        ("market", ["2330"], date(2026, 5, 18), date(2026, 6, 1)),
        ("financial", ["2330"], date(2020, 6, 2), date(2026, 6, 1)),
        ("valuation", ["2330"], date(2026, 5, 2), date(2026, 6, 1)),
    ]


def test_data_operations_service_handles_schedule_sources_and_cleanup() -> None:
    saved_configs = []
    cleanup_calls = []

    class FakeSource:
        def __init__(self, name: str) -> None:
            self.name = name

        def model_dump(self, mode="json"):
            return {"name": self.name}

    class FakeNewsSourceStore:
        def load(self):
            return [FakeSource("twse")]

    class FakeScheduleStore:
        def load(self):
            return SimpleNamespace(model_dump=lambda mode="json": {"enabled": False})

        def save(self, config):
            saved_configs.append(config)
            return SimpleNamespace(model_dump=lambda mode="json": {"enabled": True})

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            cleanup_calls.append(("runs_session", session))

        def delete_failed(self):
            cleanup_calls.append(("delete_failed",))
            return 1

        def clear_orphan_report_refs(self):
            cleanup_calls.append(("clear_orphan_report_refs",))
            return 2

        def mark_stale_running_failed(self, before, reason):
            cleanup_calls.append(("mark_stale_running_failed", before, reason))
            return 3

        def delete_before(self, before):
            cleanup_calls.append(("delete_runs_before", before))
            return 4

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            cleanup_calls.append(("reports_session", session))

        def delete_before(self, before):
            cleanup_calls.append(("delete_reports_before", before))
            return 5

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = DataOperationsApiService(
        session_scope_factory=fake_session_scope,
        news_source_store_cls=FakeNewsSourceStore,
        schedule_config_store_cls=FakeScheduleStore,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        report_repository_cls=FakeReportRepository,
    )
    stale_before = datetime(2026, 5, 1, 8, 0, 0)
    runs_before = datetime(2026, 4, 1, 8, 0, 0)
    reports_before = datetime(2026, 3, 1, 8, 0, 0)

    assert service.list_news_sources() == [{"name": "twse"}]
    assert service.get_schedule() == {"enabled": False}
    assert service.update_schedule({"enabled": True}) == {"enabled": True}
    assert saved_configs == [{"enabled": True}]
    assert service.maintenance_cleanup(
        failed_runs=True,
        orphan_report_refs=True,
        stale_running_before=stale_before,
        runs_before=runs_before,
        reports_before=reports_before,
    ) == {
        "failed_runs_deleted": 1,
        "orphan_report_refs_cleared": 2,
        "stale_running_marked_failed": 3,
        "old_runs_deleted": 4,
        "old_reports_deleted": 5,
    }
    assert cleanup_calls == [
        ("runs_session", "session"),
        ("reports_session", "session"),
        ("delete_failed",),
        ("clear_orphan_report_refs",),
        ("mark_stale_running_failed", stale_before, "marked failed by maintenance cleanup"),
        ("delete_runs_before", runs_before),
        ("delete_reports_before", reports_before),
    ]
