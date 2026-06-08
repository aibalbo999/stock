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


def test_sync_report_generation_service_records_background_hint_for_pre_refresh() -> None:
    captured = {"updated_payloads": []}
    response = ReportResponse(
        title="AI 產業鏈 自動分析報告",
        markdown="# AI 產業鏈 自動分析報告",
    )

    class FakeIngestionPipeline:
        def __init__(self) -> None:
            raise AssertionError("sync report must not run network refresh")

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
    assert "source_count" not in captured["build_kwargs"]
    ingestion = captured["updated_payloads"][0][1]["ingestion"]
    assert ingestion == {
        "status": "skipped",
        "reason": "sync_report_pre_refresh_requires_background_task",
        "action": "use_background_task",
        "requested_tickers": ["2330"],
        "background_task_endpoint": "POST /reports/generate_async",
        "data_operation_endpoint": "POST /tasks/data-operation",
        "data_operation_payload": {
            "operation": "market_refresh",
            "payload": {"tickers": ["2330"]},
        },
    }
    assert "failed" not in captured


def test_sync_report_generation_service_records_background_hint_for_quality_recovery() -> None:
    captured = {"updated_payloads": []}

    class FakeRecoveryPipeline:
        def __init__(self) -> None:
            raise AssertionError("sync report must not run market quality recovery")

    class FakeBuildService:
        calls = 0

        def build(self, request, *, company_filing_sufficient_count=None):
            FakeBuildService.calls += 1
            quality_gate = {
                "status": "caution",
                "warnings": ["股價日期不一致，最新可取得交易日未覆蓋多數股票"],
                "metrics": {
                    "market_latest_trade_date_coverage": 0.5,
                    "market_older_than_database_latest_count": 1,
                },
            }
            response = ReportResponse(title="first", markdown="# first")
            return {
                "response": response,
                "quality_gate": quality_gate,
                "evidence_count": 3,
                "report_execution": {"build_calls": FakeBuildService.calls},
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
            captured["stored_response"] = report_response
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
        quality_recovery_pipeline_cls=FakeRecoveryPipeline,
    )
    request = ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=7)

    result = service.generate(request)

    assert FakeBuildService.calls == 1
    assert result.title == "first"
    assert captured["stored_response"].title == "first"
    payload = captured["updated_payloads"][0][1]
    assert payload["quality_gate"]["status"] == "caution"
    assert payload["quality_recovery"]["status"] == "skipped"
    assert payload["quality_recovery"]["reason"] == (
        "sync_report_quality_recovery_requires_background_task"
    )
    assert payload["quality_recovery"]["action"] == "use_background_task"
    assert payload["quality_recovery"]["background_task_endpoint"] == (
        "POST /reports/generate_async"
    )
    assert payload["quality_recovery"]["data_operation_endpoint"] == (
        "POST /tasks/data-operation"
    )
    assert payload["quality_recovery"]["data_operation_payload"] == {
        "operation": "market_refresh",
        "payload": {"tickers": ["2330"]},
    }
    assert payload["quality_recovery"]["quality_gate_before"]["status"] == "caution"
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
