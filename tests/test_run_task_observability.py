from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core.time import utc_now_naive
from app.services.run_task_api import RunTaskApiService


def test_run_task_api_summarizes_recent_task_health() -> None:
    now = utc_now_naive()
    runs = [
        SimpleNamespace(
            id=1,
            source="celery_data_operation",
            status="success",
            payload={"task": "data_operation", "operation": "market_refresh"},
            report_id=None,
            error=None,
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=8),
        ),
        SimpleNamespace(
            id=2,
            source="celery_report",
            status="failed",
            payload={"celery_task_id": "task-failed"},
            report_id=None,
            error="boom",
            started_at=now - timedelta(minutes=7),
            finished_at=now - timedelta(minutes=6),
        ),
        SimpleNamespace(
            id=3,
            source="celery_report",
            status="running",
            payload={"celery_task_id": "task-running"},
            report_id=None,
            error=None,
            started_at=now - timedelta(minutes=90),
            finished_at=None,
        ),
    ]

    class FakeRunRepository:
        def __init__(self, session: object) -> None:
            assert session == "session"

        def since(self, started_at: datetime, limit: int):
            assert started_at is not None
            assert limit == 500
            return runs

    @contextmanager
    def fake_session_scope():
        yield "session"

    def serialize_run(run) -> dict:
        return {
            "id": run.id,
            "source": run.source,
            "status": run.status,
            "payload": run.payload,
            "report_id": run.report_id,
            "error": run.error,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    service = RunTaskApiService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRunRepository,
        serialize_run_func=serialize_run,
        settings_provider=lambda: SimpleNamespace(task_observability_stale_minutes=60),
    )

    summary = service.task_summary(days=1)

    assert summary["totals"]["run_count"] == 3
    assert summary["totals"]["success_count"] == 1
    assert summary["totals"]["failed_count"] == 1
    assert summary["totals"]["running_count"] == 1
    assert summary["totals"]["stale_running_count"] == 1
    assert summary["by_operation"][0] == {"operation": "celery_report", "count": 2}
    assert summary["recent_failures"][0]["task_id"] == "task-failed"
    assert summary["stale_running"][0]["task_id"] == "task-running"
