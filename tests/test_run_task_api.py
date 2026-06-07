from __future__ import annotations

import json
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
    def __init__(
        self,
        status: str,
        ready: bool,
        successful: bool,
        result: object,
        info: object | None = None,
    ) -> None:
        self.status = status
        self._ready = ready
        self._successful = successful
        self.result = result
        self.info = info

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


def _data_run(run_id: int = 21) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        source="celery_data_operation",
        status="failed",
        payload_json=(
            '{"task":"data_operation","operation":"market_refresh",'
            '"payload":{"tickers":["2330"]},"celery_task_id":"task-data"}'
        ),
        report_id=None,
        output_path=None,
        error="upstream timeout",
        started_at=datetime(2026, 5, 24, 4, 52, 33),
        finished_at=datetime(2026, 5, 24, 4, 52, 50),
    )


def _follow_up_run(run_id: int = 22) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        source="follow_up_api",
        status="failed",
        payload_json=json.dumps(
            {
                "source_report_id": 7,
                "purpose": "tracking",
                "force_refresh": True,
                "rerun_report_requested": False,
                "news_limit": 12,
                "record_noop": True,
                "celery_task_id": "task-followup",
            }
        ),
        report_id=None,
        output_path=None,
        error="follow-up failed",
        started_at=datetime(2026, 5, 24, 4, 52, 33),
        finished_at=datetime(2026, 5, 24, 4, 52, 50),
    )


def _after_close_run(run_id: int = 23) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        source="celery_after_close",
        status="failed",
        payload_json=json.dumps(
            {
                "task": "after_close_report_update",
                "source_report_id": 7,
                "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
                "celery_task_id": "task-after-close",
            }
        ),
        report_id=None,
        output_path=None,
        error="after close failed",
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
    assert captured["payload"] == {
        "topic": "AI 產業鏈",
        "tickers": ["2330"],
        "lookback_days": 7,
        "evidence_limit": 40,
        "investor_capital": 1000000,
        "beginner_mode": True,
        "investor_profile": "beginner",
        "max_position_pct": 0.1,
        "cash_reserve_pct": 0.3,
    }


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
    assert status["progress"]["status"] == "success"
    assert status["progress"]["progress_pct"] == 1.0


def test_run_task_service_reports_queued_progress_before_run_exists() -> None:
    class FakeCeleryApp:
        def AsyncResult(self, task_id):
            assert task_id == "task-pending"
            return FakeTaskResult("PENDING", False, False, None)

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            assert task_id == "task-pending"
            return None

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        celery_app=FakeCeleryApp(),
    )

    status = service.get_task_status("task-pending")

    assert status["status"] == "PENDING"
    assert status["ready"] is False
    assert "run" not in status
    assert status["progress"] == {
        "status": "queued",
        "progress_pct": 0.0,
        "current_step": "waiting_for_worker",
        "resume_hint": "任務已送出，等待 Celery worker 建立 analysis run。",
    }


def test_run_task_service_prefers_celery_progress_before_run_exists() -> None:
    celery_progress = {
        "status": "running",
        "progress_pct": 0.4,
        "current_step": "market_data_refresh",
        "resume_hint": None,
    }

    class FakeCeleryApp:
        def AsyncResult(self, task_id):
            assert task_id == "task-started"
            return FakeTaskResult(
                "STARTED",
                False,
                False,
                None,
                info={"progress": celery_progress},
            )

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            assert task_id == "task-started"
            return None

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        celery_app=FakeCeleryApp(),
    )

    status = service.get_task_status("task-started")

    assert status["status"] == "STARTED"
    assert status["progress"] == celery_progress


def test_run_task_service_reports_failure_progress_before_run_exists() -> None:
    class FakeCeleryApp:
        def AsyncResult(self, task_id):
            assert task_id == "task-failed"
            return FakeTaskResult("FAILURE", True, False, RuntimeError("boom"))

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            assert task_id == "task-failed"
            return None

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        celery_app=FakeCeleryApp(),
    )

    status = service.get_task_status("task-failed")

    assert status["ready"] is True
    assert status["successful"] is False
    assert status["error"] == "boom"
    assert status["progress"]["status"] == "failed"
    assert status["progress"]["current_step"] == "task_failed"


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


def test_run_task_service_cancels_task_and_marks_run_payload() -> None:
    captured = {}
    data_run = _data_run()

    class FakeControl:
        def revoke(self, task_id: str, terminate: bool = False) -> None:
            captured["revoke"] = (task_id, terminate)

    class FakeCeleryApp:
        control = FakeControl()

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            return data_run if task_id == "task-data" else None

        def update_payload(self, run_id: int, payload: dict):
            captured["update_payload"] = (run_id, payload)
            data_run.payload_json = json.dumps(payload)
            return data_run

        def get(self, run_id: int):
            return data_run if run_id == data_run.id else None

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        celery_app=FakeCeleryApp(),
    )

    response = service.cancel_task("task-data")

    assert response["cancel_requested"] is True
    assert response["run"]["id"] == data_run.id
    assert captured["revoke"] == ("task-data", False)
    assert captured["update_payload"][1]["cancel_requested"] is True


def test_run_task_service_retries_data_operation_from_run_payload() -> None:
    captured = {}

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            return _data_run() if task_id == "task-data" else None

    class FakeTask:
        def delay(self, payload):
            captured["payload"] = payload
            return SimpleNamespace(id="task-retry")

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        data_operation_task=FakeTask(),
    )

    response = service.retry_task("task-data")

    assert response["task_id"] == "task-retry"
    assert response["retried_from_task_id"] == "task-data"
    assert captured["payload"] == {
        "operation": "market_refresh",
        "payload": {"tickers": ["2330"]},
    }


def test_run_task_service_retries_follow_up_with_original_options() -> None:
    captured = {}

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            return _follow_up_run() if task_id == "task-followup" else None

    class FakeTask:
        def delay(self, payload):
            captured["payload"] = payload
            return SimpleNamespace(id="task-followup-retry")

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        report_follow_up_task=FakeTask(),
    )

    response = service.retry_task("task-followup")

    assert response["task_id"] == "task-followup-retry"
    assert response["retried_from_task_id"] == "task-followup"
    assert response["retried_from_run_id"] == 22
    assert captured["payload"] == {
        "report_id": 7,
        "payload": {
            "purpose": "tracking",
            "force_refresh": True,
            "record_noop": True,
            "news_limit": 12,
            "rerun_report": False,
        },
    }


def test_run_task_service_does_not_retry_after_close_task_as_follow_up() -> None:
    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def get_by_celery_task_id(self, task_id: str):
            return _after_close_run() if task_id == "task-after-close" else None

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
    )

    with pytest.raises(AsyncReportValidationError, match="not retryable"):
        service.retry_task("task-after-close")
