from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core.time import utc_now_naive
from app.services import run_task_api as run_task_api_module
from app.services import run_task_api_summary
from app.services.run_task_api import RunTaskApiService


def test_run_task_api_reexports_dedicated_summary_helpers() -> None:
    assert run_task_api_module._alert_sort_key is run_task_api_summary.alert_sort_key
    assert RunTaskApiService._run_summary_row is run_task_api_summary.run_summary_row
    assert RunTaskApiService._task_failure_alerts is run_task_api_summary.task_failure_alerts
    assert (
        RunTaskApiService._task_failure_diagnostic is run_task_api_summary.task_failure_diagnostic
    )
    assert RunTaskApiService._celery_status_progress is run_task_api_summary.celery_status_progress


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
        SimpleNamespace(
            id=4,
            source="celery_data_operation",
            status="failed",
            payload_json=json.dumps(
                {
                    "task": "data_operation",
                    "operation": "company_filings_fetch",
                    "payload": {"tickers": ["2330"]},
                    "celery_task_id": "task-filing",
                }
            ),
            report_id=None,
            error="MOPS returned HTTP 403 captcha",
            started_at=now - timedelta(days=1, minutes=3),
            finished_at=now - timedelta(days=1, minutes=2),
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

    summary = service.task_summary(days=2)

    assert summary["totals"]["run_count"] == 4
    assert summary["totals"]["success_count"] == 1
    assert summary["totals"]["failed_count"] == 2
    assert summary["totals"]["running_count"] == 1
    assert summary["totals"]["stale_running_count"] == 1
    assert summary["by_operation"][0] == {"operation": "celery_report", "count": 2}
    assert summary["by_operation"][1] == {"operation": "company_filings_fetch", "count": 1}
    assert summary["by_operation"][2] == {"operation": "market_refresh", "count": 1}
    assert summary["by_error_category"] == [
        {"error_category": "data_source", "severity": "warning", "count": 1},
        {"error_category": "quota", "severity": "warning", "count": 1},
    ]
    assert summary["error_category_daily"] == [
        {
            "date": (now - timedelta(days=1, minutes=3)).date().isoformat(),
            "error_category": "data_source",
            "severity": "warning",
            "count": 1,
        },
        {
            "date": (now - timedelta(minutes=7)).date().isoformat(),
            "error_category": "quota",
            "severity": "warning",
            "count": 1,
        },
    ]
    assert summary["alerts"] == [
        {
            "severity": "warning",
            "code": "task_stale_running",
            "error_category": "stale_running",
            "count": 1,
            "days": 0,
            "message": "有 1 個背景任務疑似卡住，請檢查 worker 與任務狀態。",
            "next_steps": [
                "查看背景任務觀測中的疑似卡住任務。",
                "確認 Celery worker 是否在線，必要時取消或重試任務。",
            ],
        }
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
        (
            "failed",
            "unsupported data operation task",
            "data_operation",
            False,
            "payload_validation",
        ),
        (
            "failed",
            "ReadTimeout while fetching documents",
            "company_filings_fetch",
            True,
            "timeout",
        ),
        ("failed", "MOPS returned HTTP 403 captcha", "company_filings_fetch", True, "data_source"),
        (
            "failed",
            "Visual RAG 後援失敗：Visual RAG vision LLM API key 或本地 gateway 尚未配置。",
            "company_filings_fetch",
            True,
            "visual_rag",
        ),
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


def test_run_task_api_visual_rag_diagnostic_points_to_runtime_status() -> None:
    diagnostic = RunTaskApiService._task_failure_diagnostic(
        status="failed",
        error="PDF 公司文件沒有可抽取文字；Visual RAG 後援失敗：RESOURCE_EXHAUSTED quota exceeded",
        operation="company_filings_fetch",
        retryable=True,
    )

    assert diagnostic["category"] == "visual_rag"
    assert diagnostic["summary"] == "Visual RAG PDF 解析後援異常"
    assert any("visual_rag_runtime" in step for step in diagnostic["next_steps"])
    assert any("免費額度" in step for step in diagnostic["next_steps"])


def test_run_task_api_alerts_on_queue_errors_and_repeated_failure_categories() -> None:
    rows = [
        {
            "error_category": "task_queue",
            "error_severity": "error",
            "error_summary": "Redis/Celery queue 或 worker 異常",
            "next_steps": ["重新啟動 Redis/Celery。"],
            "stale_running": False,
        },
        {
            "error_category": "data_source",
            "error_severity": "warning",
            "error_summary": "市場資料、公司文件或新聞來源異常",
            "next_steps": ["檢查資料源 token。"],
            "stale_running": False,
        },
        {
            "error_category": "data_source",
            "error_severity": "warning",
            "error_summary": "市場資料、公司文件或新聞來源異常",
            "next_steps": ["檢查資料源 token。"],
            "stale_running": False,
        },
    ]
    daily_rows = [
        {"date": "2026-06-07", "error_category": "task_queue", "severity": "error", "count": 1},
        {"date": "2026-06-07", "error_category": "data_source", "severity": "warning", "count": 1},
        {"date": "2026-06-08", "error_category": "data_source", "severity": "warning", "count": 1},
    ]

    alerts = RunTaskApiService._task_failure_alerts(rows, daily_rows)

    assert alerts[0]["severity"] == "error"
    assert alerts[0]["code"] == "task_failure_task_queue"
    assert alerts[0]["count"] == 1
    assert alerts[1]["severity"] == "warning"
    assert alerts[1]["code"] == "task_failure_data_source"
    assert alerts[1]["count"] == 2
    assert alerts[1]["days"] == 2
    assert "2 天內重複出現 2 次" in alerts[1]["message"]


def test_run_task_api_summary_prefers_persisted_failure_diagnostics() -> None:
    now = utc_now_naive()
    run = {
        "id": 44,
        "source": "celery",
        "status": "failed",
        "payload": json.dumps(
            {
                "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
                "celery_task_id": "task-persisted",
                "task_failure_diagnostic": {
                    "operation": "report_generation",
                    "error_category": "data_source",
                    "error_severity": "warning",
                    "error_summary": "持久化資料源診斷",
                    "next_steps": ["使用持久化建議。"],
                    "retryable": True,
                    "retry_kind": "report_generation",
                    "retry_endpoint": "POST /tasks/task-persisted/retry",
                    "status_endpoint": "GET /tasks/task-persisted",
                    "run_endpoint": "GET /runs/44",
                    "next_action": "使用持久化 next action",
                },
            }
        ),
        "report_id": None,
        "error": "RESOURCE_EXHAUSTED quota exceeded",
        "started_at": now.isoformat(),
        "finished_at": now.isoformat(),
    }

    row = RunTaskApiService._run_summary_row(run, stale_after_minutes=60, now=now)

    assert row["error_category"] == "data_source"
    assert row["error_summary"] == "持久化資料源診斷"
    assert row["next_steps"] == ["使用持久化建議。"]
    assert row["next_action"] == "使用持久化 next action"
