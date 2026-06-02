from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.models.schemas import ReportRequest, ReportResponse
from app.services.report_generation_api import SyncReportGenerationApiService
from app.services.report_generator import ReportExecutionError


def test_sync_report_generation_service_records_run_and_report_payload() -> None:
    captured = {"updated_payloads": []}
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown="# AI 產業鏈 自動分析報告",
    )

    class FakeBuildService:
        def build(self, request, *, company_filing_sufficient_count=None):
            captured["build_request"] = request
            captured["company_filing_sufficient_count"] = company_filing_sufficient_count
            return {
                "response": response,
                "quality_gate": {"status": "ready"},
                "evidence_count": 3,
                "report_execution": {"llm_enabled": True},
            }

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def start(self, source: str, payload: dict):
            captured["start"] = {"source": source, "payload": payload}
            return SimpleNamespace(id=11)

        def update_payload(self, run_id: int, payload: dict) -> None:
            captured["updated_payloads"].append((run_id, payload))

        def mark_success(self, run_id: int, report_id: int) -> None:
            captured["success"] = {"run_id": run_id, "report_id": report_id}

        def mark_failed(self, run_id: int, error: str) -> None:
            captured["failed"] = {"run_id": run_id, "error": error}

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def create(self, request, report_response):
            captured["stored"] = {"request": request, "response": report_response}
            return SimpleNamespace(id=77)

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = SyncReportGenerationApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        report_repository_cls=FakeReportRepository,
        report_build_service_factory=FakeBuildService,
        count_sufficient_company_filings_func=lambda tickers: 2,
    )
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=7)

    result = service.generate(request)

    assert result is response
    assert captured["start"]["source"] == "api_sync"
    assert captured["start"]["payload"]["topic"] == "AI 產業鏈"
    assert captured["company_filing_sufficient_count"] == 2
    assert captured["stored"] == {"request": request, "response": response}
    assert captured["updated_payloads"] == [
        (
            11,
            {
                "request": request.model_dump(mode="json"),
                "quality_gate": {"status": "ready"},
                "evidence_count": 3,
                "report_execution": {"llm_enabled": True},
            },
        )
    ]
    assert captured["success"] == {"run_id": 11, "report_id": 77}
    assert "failed" not in captured


def test_sync_report_generation_service_refreshes_data_before_build() -> None:
    captured = {"updated_payloads": []}
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown="# AI 產業鏈 自動分析報告",
    )

    class FakeIngestionPipeline:
        async def pre_report_refresh(self, request):
            captured["refresh_request"] = request
            return {"news": {"count": 7}, "market": {"stored": [{"ticker": "2330"}]}}

    class FakeBuildService:
        def build(self, request, **kwargs):
            captured["build_kwargs"] = kwargs
            return {
                "response": response,
                "quality_gate": {"status": "ready"},
                "evidence_count": 3,
                "report_execution": {"llm_enabled": True},
            }

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def start(self, source: str, payload: dict):
            return SimpleNamespace(id=11)

        def update_payload(self, run_id: int, payload: dict) -> None:
            captured["updated_payloads"].append((run_id, payload))

        def mark_success(self, run_id: int, report_id: int) -> None:
            captured["success"] = {"run_id": run_id, "report_id": report_id}

        def mark_failed(self, run_id: int, error: str) -> None:
            captured["failed"] = {"run_id": run_id, "error": error}

    class FakeReportRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def create(self, request, report_response):
            return SimpleNamespace(id=77)

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = SyncReportGenerationApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        report_repository_cls=FakeReportRepository,
        report_build_service_factory=FakeBuildService,
        count_sufficient_company_filings_func=lambda tickers: 1,
        ingestion_pipeline_cls=FakeIngestionPipeline,
    )
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=7)

    result = service.generate(request)

    assert result is response
    assert captured["refresh_request"] == request
    assert captured["build_kwargs"]["source_count"] == 7
    assert captured["updated_payloads"][0][1]["ingestion"]["market"]["stored"] == [{"ticker": "2330"}]
    assert "failed" not in captured


def test_sync_report_generation_service_marks_run_failed_on_execution_error() -> None:
    captured = {}

    class FailingBuildService:
        def build(self, request, *, company_filing_sufficient_count=None):
            raise ReportExecutionError("bad report")

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def start(self, source: str, payload: dict):
            return SimpleNamespace(id=11)

        def mark_failed(self, run_id: int, error: str) -> None:
            captured["failed"] = {"run_id": run_id, "error": error}

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = SyncReportGenerationApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        report_repository_cls=object,
        report_build_service_factory=FailingBuildService,
        count_sufficient_company_filings_func=lambda tickers: 0,
    )

    with pytest.raises(ReportExecutionError, match="bad report"):
        service.generate(ReportRequest(topic="AI", tickers=["2330"]))

    assert captured["failed"] == {"run_id": 11, "error": "bad report"}
