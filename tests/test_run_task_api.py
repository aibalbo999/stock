from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.schemas import ReportRequest
from app.services.run_task_api import (
    AsyncReportValidationError,
    RunTaskApiService,
    RunTaskNotFound,
    TaskQueueUnavailableError,
)


class FakeTaskResult:
    def __init__(self, status: str, ready: bool, successful: bool, result: object) -> None:
        self.status = status
        self._ready = ready
        self._successful = successful
        self.result = result

    def ready(self) -> bool:
        return self._ready

    def successful(self) -> bool:
        return self._successful


def _run(run_id: int = 19) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        source="celery",
        status="success",
        payload_json='{"celery_task_id": "task-linked"}',
        report_id=11,
        output_path="reports/demo.md",
        error=None,
        started_at=datetime(2026, 5, 24, 4, 52, 33),
        finished_at=datetime(2026, 5, 24, 4, 52, 50),
    )


def _run_with_workflow(run_id: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        source="pipeline_api",
        status="failed",
        payload_json=(
            '{"workflow":{"name":"standard_report_pipeline","status":"failed",'
            '"current_step":"report_build","steps":['
            '{"name":"pre_report_refresh","status":"success"},'
            '{"name":"report_build","status":"failed"},'
            '{"name":"auto_follow_up","status":"pending"}]}}'
        ),
        report_id=None,
        output_path=None,
        error="report build failed",
        started_at=datetime(2026, 5, 24, 4, 52, 33),
        finished_at=datetime(2026, 5, 24, 4, 52, 50),
    )


def test_run_task_service_queues_async_report_after_whitelist_check() -> None:
    captured = {}

    class FakeMapper:
        def filter_allowed_tickers(self, tickers):
            captured["tickers"] = tickers
            return ["2330"]

    class FakeReportTask:
        def delay(self, payload):
            captured["payload"] = payload
            return SimpleNamespace(id="task-123")

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        entity_mapper_cls=FakeMapper,
        report_task=FakeReportTask(),
    )

    result = service.generate_report_async(
        ReportRequest(topic="AI 產業鏈", tickers=["2330"], lookback_days=7)
    )

    assert result == {"task_id": "task-123", "status": "queued"}
    assert captured["tickers"] == ["2330"]
    assert captured["payload"]["topic"] == "AI 產業鏈"
    assert captured["payload"]["tickers"] == ["2330"]


def test_run_task_service_queues_discovered_report_data_operation_and_follow_up() -> None:
    captured = {}

    class FakeTask:
        def __init__(self, name: str) -> None:
            self.name = name

        def delay(self, payload):
            captured[self.name] = payload
            return SimpleNamespace(id=f"{self.name}-task")

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        discovered_report_task=FakeTask("discovered"),
        data_operation_task=FakeTask("data"),
        report_follow_up_task=FakeTask("followup"),
    )

    discovered = service.generate_discovered_report_async({"topic": "AI 產業鏈", "lookback_days": 14})
    data = service.queue_data_operation("market_refresh", {"tickers": ["2330"]})
    follow_up = service.queue_report_follow_up(7, {"purpose": "required", "rerun_report": True})

    assert discovered == {
        "task_id": "discovered-task",
        "status": "queued",
        "operation": "run_discovered",
    }
    assert captured["discovered"]["topic"] == "AI 產業鏈"
    assert data == {
        "task_id": "data-task",
        "status": "queued",
        "operation": "market_refresh",
    }
    assert captured["data"] == {"operation": "market_refresh", "payload": {"tickers": ["2330"]}}
    assert follow_up == {
        "task_id": "followup-task",
        "status": "queued",
        "operation": "report_follow_up",
        "report_id": 7,
    }
    assert captured["followup"] == {
        "report_id": 7,
        "payload": {"purpose": "required", "rerun_report": True},
    }


def test_run_task_service_maps_task_submit_failures_to_queue_unavailable() -> None:
    class BrokenTask:
        def delay(self, payload):
            raise ConnectionError("redis down")

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        data_operation_task=BrokenTask(),
    )

    with pytest.raises(TaskQueueUnavailableError, match="data operation market_refresh"):
        service.queue_data_operation("market_refresh", {"tickers": ["2330"]})


def test_run_task_service_rejects_missing_or_dropped_async_tickers() -> None:
    class FakeMapper:
        def __init__(self, allowed):
            self.allowed = allowed

        def filter_allowed_tickers(self, tickers):
            return self.allowed

    @contextmanager
    def fake_session_scope():
        yield "session"

    empty_service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        entity_mapper_cls=lambda: FakeMapper([]),
        report_task=SimpleNamespace(delay=lambda payload: None),
    )
    with pytest.raises(AsyncReportValidationError, match="requires at least one"):
        empty_service.generate_report_async(ReportRequest(topic="AI", tickers=[]))

    dropped_service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        entity_mapper_cls=lambda: FakeMapper(["2330"]),
        report_task=SimpleNamespace(delay=lambda payload: None),
    )
    with pytest.raises(AsyncReportValidationError, match="outside the static whitelist"):
        dropped_service.generate_report_async(ReportRequest(topic="AI", tickers=["2330", "9999"]))


def test_run_task_service_gets_task_status_with_linked_run() -> None:
    class FakeCeleryApp:
        def AsyncResult(self, task_id):
            assert task_id == "task-linked"
            return FakeTaskResult("SUCCESS", True, True, {"run_id": 19})

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            assert task_id == "task-linked"
            return _run()

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        celery_app=FakeCeleryApp(),
    )

    status = service.get_task_status("task-linked")

    assert status["task_id"] == "task-linked"
    assert status["status"] == "SUCCESS"
    assert status["successful"] is True
    assert status["result"] == {"run_id": 19}
    assert status["run"]["id"] == 19
    assert status["run"]["workflow"] is None
    assert status["run"]["workflow_summary"] is None


def test_run_task_service_lists_gets_and_deletes_runs() -> None:
    deleted = []

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def latest(self, limit: int):
            assert limit == 2
            return [_run(1)]

        def get(self, run_id: int):
            return _run(run_id) if run_id == 1 else None

        def delete(self, run_id: int) -> bool:
            deleted.append(run_id)
            return run_id == 1

        def get_by_celery_task_id(self, task_id: str):
            return _run(19) if task_id == "task-linked" else None

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
    )

    assert service.list_runs(2)[0]["id"] == 1
    assert service.get_run(1)["id"] == 1
    assert service.get_run_by_task_id("task-linked")["id"] == 19
    assert service.delete_run(1) == {"deleted": True, "id": 1}
    with pytest.raises(RunTaskNotFound, match="run not found"):
        service.get_run(2)
    with pytest.raises(RunTaskNotFound, match="run not found for task"):
        service.get_run_by_task_id("missing")
    assert deleted == [1]


def test_run_task_service_serializes_workflow_resume_summary() -> None:
    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def latest(self, limit: int):
            assert limit == 1
            return [_run_with_workflow()]

        def get(self, run_id: int):
            return _run_with_workflow(run_id)

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
    )

    payload = service.list_runs(1)[0]

    assert payload["workflow"]["name"] == "standard_report_pipeline"
    assert payload["workflow_summary"]["status"] == "failed"
    assert payload["workflow_summary"]["completed_steps_count"] == 1
    assert payload["workflow_summary"]["failed_steps_count"] == 1
    assert payload["workflow_summary"]["resume_from_step"] == "report_build"
    assert payload["workflow_summary"]["resumable"] is True
    assert payload["workflow_summary"]["resume_hint"] == "可從 report_build 重新啟動或人工接續。"
