from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

from app.models.schemas import FinancialMetric, MarketSnapshot, ReportRequest, ReportResponse
from app.services.company_data_audit_api import CompanyDataAuditApiService
from app.services import report_quality
from app.services.discovered_market_data import (
    merge_financial_metric_history,
    merge_latest_by_ticker,
)
from app.services.report_build import ReportBuildService
from app.services.report_followup import serialize_run
from app.services.report_generation_api import SyncReportGenerationApiService
from app.services.report_quality import build_quality_gate_for_request


class DummyRun:
    id = 19
    source = "celery"
    status = "success"
    payload_json = '{"celery_task_id": "task-linked"}'
    report_id = 11
    output_path = "reports/demo.md"
    error = None
    started_at = datetime(2026, 5, 24, 4, 52, 33)
    finished_at = datetime(2026, 5, 24, 4, 52, 50)


def test_serialize_run_exposes_parsed_workflow() -> None:
    run = SimpleNamespace(
        id=1,
        source="pipeline_api",
        status="success",
        payload_json=(
            '{"workflow":{"name":"standard_report_pipeline","status":"success"},'
            '"workflow_orchestration":{"mode":"prefect_flow","executed_engine":"prefect"}}'
        ),
        report_id=2,
        output_path=None,
        error=None,
        started_at=datetime(2026, 5, 31, 9, 0, 0),
        finished_at=datetime(2026, 5, 31, 9, 1, 0),
    )

    serialized = serialize_run(run)

    assert serialized["workflow"] == {
        "name": "standard_report_pipeline",
        "status": "success",
    }
    assert serialized["workflow_orchestration"] == {
        "mode": "prefect_flow",
        "executed_engine": "prefect",
    }


def test_merge_latest_by_ticker_uses_cached_data_when_fetch_fails() -> None:
    cached = [
        MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 29), close=1200.0),
        MarketSnapshot(ticker="2382", trade_date=date(2026, 5, 29), close=300.0),
    ]
    fetched = [MarketSnapshot(ticker="2330", trade_date=date(2026, 5, 30), close=1210.0)]

    merged = merge_latest_by_ticker(["2330", "2382"], fetched, cached, "trade_date")

    assert [snapshot.ticker for snapshot in merged] == ["2330", "2382"]
    assert [snapshot.close for snapshot in merged] == [1210.0, 300.0]


def test_merge_financial_metric_history_dedupes_cached_and_fetched_rows() -> None:
    cached = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="income",
            metric="revenue",
            value=100.0,
            source="test",
        )
    ]
    fetched = [
        FinancialMetric(
            ticker="2330",
            report_date=date(2026, 3, 31),
            statement_type="income",
            metric="revenue",
            value=110.0,
            source="test",
        ),
        FinancialMetric(
            ticker="2382",
            report_date=date(2026, 3, 31),
            statement_type="income",
            metric="revenue",
            value=50.0,
            source="test",
        ),
    ]

    merged = merge_financial_metric_history(fetched, cached)
    values = {(metric.ticker, metric.metric): metric.value for metric in merged}

    assert values == {("2330", "revenue"): 110.0, ("2382", "revenue"): 50.0}


def test_generate_report_sync_attaches_quality_gate_from_used_evidence() -> None:
    captured = {"updated_payloads": []}

    class FakeGenerator:
        def __init__(self) -> None:
            self.last_evidence_documents = ["used-doc"]

        def generate(self, request) -> ReportResponse:
            assert request.topic == "AI 產業鏈"
            return ReportResponse(
                title="AI 產業鏈 自動分析報告",
                markdown="# AI 產業鏈 自動分析報告\n\n## 一頁摘要\n- 測試",
            )

    class FakeReport:
        id = 77

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def create(self, request, response) -> FakeReport:
            captured["stored_quality_gate"] = response.quality_gate
            return FakeReport()

    class FakeAnalysisRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def start(self, source: str, payload: dict) -> DummyRun:
            assert source == "api_sync"
            captured["start_payload"] = payload
            return DummyRun()

        def update_payload(self, run_id: int, payload: dict) -> None:
            assert run_id == DummyRun.id
            captured["updated_payloads"].append(payload)

        def mark_success(self, run_id: int, report_id: int) -> None:
            assert run_id == DummyRun.id
            assert report_id == FakeReport.id
            captured["marked_success"] = True

        def mark_failed(self, run_id: int, error: str) -> None:
            captured["failed"] = error

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_quality_gate_for_request(
        request,
        documents=None,
        source_count=None,
        llm_result=None,
        company_filing_sufficient_count=None,
    ) -> dict:
        captured["quality_documents"] = documents
        captured["quality_source_count"] = source_count
        captured["quality_llm_result"] = llm_result
        captured["quality_company_filing_sufficient_count"] = company_filing_sufficient_count
        return {
            "status": "ready",
            "blockers": [],
            "warnings": [],
            "action_policy": {"policy": "actionable", "label": "通過品質門檻"},
            "metrics": {
                "promoted_count": 1,
                "candidate_supported_ratio": 1,
                "dynamic_source_count": 1,
                "market_coverage": 1,
                "monthly_revenue_coverage": 1,
                "valuation_coverage": 1,
            },
            "recommendation": "資料品質達到本系統產出投資建議的基本門檻。",
        }

    service = SyncReportGenerationApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeAnalysisRunRepository,
        report_repository_cls=FakeReportRepository,
        report_build_service_factory=lambda: ReportBuildService(
            report_generator_cls=FakeGenerator,
            build_quality_gate_for_request_func=fake_quality_gate_for_request,
            report_execution_summary_func=lambda generator: {},
        ),
        count_sufficient_company_filings_func=lambda tickers: 1,
    )
    result = service.generate(ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=7))

    assert result.quality_gate["status"] == "ready"
    assert "## 報告品質門檻" in result.markdown
    assert captured["quality_documents"] == ["used-doc"]
    assert captured["quality_source_count"] is None
    assert captured["stored_quality_gate"]["status"] == "ready"
    assert captured["updated_payloads"][0]["evidence_count"] == 1
    assert captured["marked_success"] is True


def test_quality_gate_for_request_uses_dynamic_request_tickers(monkeypatch) -> None:
    captured = {}

    def fake_build_report_quality_gate(source_audit, promoted_tickers, **kwargs):
        captured["promoted_tickers"] = promoted_tickers
        return {"status": "ready", "metrics": {"promoted_count": len(promoted_tickers)}}

    class FakeMarketRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return []

        def history_by_tickers(self, tickers, limit=90):
            return {}

    class EmptyRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return []

        def by_tickers(self, tickers):
            return []

        def history_by_tickers(self, tickers, limit=18):
            return {}

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(report_quality, "build_report_quality_gate", fake_build_report_quality_gate)
    monkeypatch.setattr("app.services.report_quality.MarketRepository", FakeMarketRepository)
    monkeypatch.setattr("app.services.report_quality.MonthlyRevenueRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.FinancialMetricRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.ValuationMetricRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.session_scope", fake_session_scope)

    gate = build_quality_gate_for_request(ReportRequest(topic="AI 產業鏈", tickers=["2059"]))

    assert gate["status"] == "ready"
    assert captured["promoted_tickers"] == ["2059"]


def test_quality_gate_for_request_marks_stale_market_cache(monkeypatch) -> None:
    captured = {}

    def fake_build_report_quality_gate(source_audit, promoted_tickers, **kwargs):
        captured.update(kwargs)
        return {"status": "caution", "metrics": kwargs}

    class FakeMarketRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return [
                SimpleNamespace(ticker=tickers[0], source="FinMind TaiwanStockPrice; cached-stale")
            ]

        def history_by_tickers(self, tickers, limit=90):
            return {}

    class FakeMonthlyRevenueRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return [
                SimpleNamespace(
                    ticker=tickers[0], source="FinMind TaiwanStockMonthRevenue; cached-stale"
                )
            ]

        def history_by_tickers(self, tickers, limit=18):
            return {}

    class FakeFinancialMetricRepository:
        def __init__(self, session):
            pass

        def by_tickers(self, tickers):
            return [
                SimpleNamespace(
                    ticker=tickers[0], source="FinMind TaiwanStockFinancialStatements; cached-stale"
                )
            ]

    class FakeValuationMetricRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return [
                SimpleNamespace(
                    ticker=tickers[0],
                    pe_ratio=20,
                    pb_ratio=5,
                    source="FinMind TaiwanStockPER; cached-stale",
                )
            ]

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(report_quality, "build_report_quality_gate", fake_build_report_quality_gate)
    monkeypatch.setattr("app.services.report_quality.MarketRepository", FakeMarketRepository)
    monkeypatch.setattr(
        "app.services.report_quality.MonthlyRevenueRepository", FakeMonthlyRevenueRepository
    )
    monkeypatch.setattr(
        "app.services.report_quality.FinancialMetricRepository", FakeFinancialMetricRepository
    )
    monkeypatch.setattr(
        "app.services.report_quality.ValuationMetricRepository", FakeValuationMetricRepository
    )
    monkeypatch.setattr("app.services.report_quality.session_scope", fake_session_scope)

    gate = build_quality_gate_for_request(ReportRequest(topic="AI 產業鏈", tickers=["2330"]))

    assert gate["metrics"]["market_stale_count"] == 1
    assert gate["metrics"]["monthly_revenue_stale_count"] == 1
    assert gate["metrics"]["financial_metrics_stale_ticker_count"] == 1
    assert gate["metrics"]["valuation_stale_count"] == 1


def test_quality_gate_for_request_can_use_revalidated_candidate_confidence(monkeypatch) -> None:
    captured = {}

    def fake_build_report_quality_gate(source_audit, promoted_tickers, **kwargs):
        captured["candidate_support"] = source_audit["candidate_support"]
        return {"status": "ready", "metrics": source_audit["candidate_support"]}

    class FakeMarketRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return []

        def history_by_tickers(self, tickers, limit=90):
            return {}

    class EmptyRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return []

        def by_tickers(self, tickers):
            return []

        def history_by_tickers(self, tickers, limit=18):
            return {}

    @contextmanager
    def fake_session_scope():
        yield object()

    support = {
        "total": 20,
        "supported": 1,
        "supported_ratio": 0.05,
        "formal_supported_ratio": 1.0,
        "formal_confidence_avg": 100,
        "formal_confidence_min": 100,
    }
    monkeypatch.setattr(report_quality, "build_report_quality_gate", fake_build_report_quality_gate)
    monkeypatch.setattr("app.services.report_quality.MarketRepository", FakeMarketRepository)
    monkeypatch.setattr("app.services.report_quality.MonthlyRevenueRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.FinancialMetricRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.ValuationMetricRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.session_scope", fake_session_scope)

    gate = build_quality_gate_for_request(
        ReportRequest(topic="機器人 產業鏈", tickers=["3037"]),
        candidate_support=support,
    )

    assert gate["metrics"]["formal_confidence_min"] == 100
    assert captured["candidate_support"]["supported_ratio"] == 0.05


def test_quality_gate_for_request_passes_runtime_rag_status(monkeypatch) -> None:
    captured = {}
    rag_status = {
        "retrieval_mode": "memory_hybrid",
        "embedding_status": {"provider": "sentence_transformers"},
        "reranker_status": {"provider": "keyword"},
    }

    def fake_build_report_quality_gate(source_audit, promoted_tickers, **kwargs):
        captured["rag_status"] = kwargs["rag_status"]
        return {"status": "ready", "metrics": {}}

    class FakeMarketRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return []

        def history_by_tickers(self, tickers, limit=90):
            return {}

    class EmptyRepository:
        def __init__(self, session):
            pass

        def latest_by_tickers(self, tickers):
            return []

        def by_tickers(self, tickers):
            return []

        def history_by_tickers(self, tickers, limit=18):
            return {}

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(report_quality, "build_report_quality_gate", fake_build_report_quality_gate)
    monkeypatch.setattr(report_quality, "rag_runtime_status", lambda: rag_status)
    monkeypatch.setattr("app.services.report_quality.MarketRepository", FakeMarketRepository)
    monkeypatch.setattr("app.services.report_quality.MonthlyRevenueRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.FinancialMetricRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.ValuationMetricRepository", EmptyRepository)
    monkeypatch.setattr("app.services.report_quality.session_scope", fake_session_scope)

    gate = build_quality_gate_for_request(ReportRequest(topic="AI 產業鏈", tickers=["2330"]))

    assert gate["status"] == "ready"
    assert captured["rag_status"] == rag_status


def test_company_data_audit_api_uses_session_scope() -> None:
    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_audit(session, report_id):
        assert isinstance(session, FakeSession)
        assert report_id == 7
        return {"status": "needs_attention", "rows": [{"ticker": "3017", "status": "partial"}]}

    service = CompanyDataAuditApiService(
        session_scope_factory=fake_session_scope,
        audit_report_company_data_func=fake_audit,
    )
    response = service.report_company_data_audit(7)

    assert response["rows"][0]["ticker"] == "3017"
