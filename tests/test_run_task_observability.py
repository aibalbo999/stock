from __future__ import annotations

import json
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
            payload_json=json.dumps(
                {
                    "task": "data_operation",
                    "operation": "market_refresh",
                    "payload": {"tickers": ["2330"]},
                    "celery_task_id": "task-success",
                }
            ),
            report_id=None,
            error=None,
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=8),
        ),
        SimpleNamespace(
            id=2,
            source="celery_report",
            status="failed",
            payload_json=json.dumps(
                {
                    "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
                    "celery_task_id": "task-failed",
                }
            ),
            report_id=None,
            error="RESOURCE_EXHAUSTED quota exceeded",
            started_at=now - timedelta(minutes=7),
            finished_at=now - timedelta(minutes=6),
        ),
        SimpleNamespace(
            id=3,
            source="celery_report",
            status="running",
            payload_json=json.dumps(
                {
                    "request": {"topic": "機器人 產業鏈", "tickers": ["1504"]},
                    "celery_task_id": "task-running",
                }
            ),
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
            "payload": run.payload_json,
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
    assert summary["by_operation"][1] == {"operation": "market_refresh", "count": 1}
    assert summary["by_error_category"] == [
        {"error_category": "quota", "severity": "warning", "count": 1}
    ]
    assert summary["recent_failures"][0]["task_id"] == "task-failed"
    assert summary["recent_failures"][0]["error_category"] == "quota"
    assert summary["recent_failures"][0]["error_severity"] == "warning"
    assert summary["recent_failures"][0]["error_summary"] == "模型/API 額度或速率限制"
    assert summary["recent_failures"][0]["next_steps"] == [
        "查看 AI 額度與模型路由或資料源額度。",
        "等待額度重置，或改用已設定的 fallback 模型/資料源後再重試。",
    ]
    assert summary["recent_failures"][0]["retryable"] is True
    assert summary["recent_failures"][0]["retry_kind"] == "report_generation"
    assert summary["recent_failures"][0]["retry_endpoint"] == "POST /tasks/task-failed/retry"
    assert summary["recent_failures"][0]["status_endpoint"] == "GET /tasks/task-failed"
    assert summary["recent_failures"][0]["run_endpoint"] == "GET /runs/2"
    assert "可從維護頁重試" in summary["recent_failures"][0]["next_action"]
    assert "查看 AI 額度" in summary["recent_failures"][0]["next_action"]
    assert summary["stale_running"][0]["task_id"] == "task-running"
    assert summary["stale_running"][0]["retry_kind"] == "report_generation"


def test_run_task_api_classifies_common_task_failure_causes() -> None:
    cases = [
        ("failed", "RESOURCE_EXHAUSTED quota exceeded", "report_generation", True, "quota"),
        ("failed", "Redis broker connection refused", "market_refresh", True, "task_queue"),
        ("failed", "unsupported data operation task", "data_operation", False, "payload_validation"),
        ("failed", "ReadTimeout while fetching documents", "company_filings_fetch", True, "timeout"),
        ("failed", "MOPS returned HTTP 403 captcha", "company_filings_fetch", True, "data_source"),
        ("cancelled", "", "report_generation", False, "cancelled"),
    ]

    for status, error, operation, retryable, expected_category in cases:
        diagnostic = RunTaskApiService._task_failure_diagnostic(
            status=status,
            error=error,
            operation=operation,
            retryable=retryable,
        )

        assert diagnostic["category"] == expected_category
        assert diagnostic["summary"]
        assert diagnostic["next_steps"]
