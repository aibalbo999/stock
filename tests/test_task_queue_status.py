from __future__ import annotations

from types import SimpleNamespace

from app.services import status_task_queue


def test_task_queue_status_reports_worker_ping_online(monkeypatch) -> None:
    fake_app = object()
    monkeypatch.setattr(status_task_queue, "_task_export_status", lambda: _export_status(fake_app))

    status = status_task_queue.task_queue_status(
        SimpleNamespace(redis_url="redis://localhost:6379/0"),
        redis_status={"ok": True},
        redact_url=lambda value: value,
        worker_ping_func=lambda app, timeout: {"celery@worker-1": {"ok": "pong"}},
    )

    assert status["ready"] is True
    assert status["processing_ready"] is True
    assert status["worker_ping_checked"] is True
    assert status["worker_online"] is True
    assert status["worker_count"] == 1
    assert status["worker_nodes"] == ["celery@worker-1"]
    assert status["worker_ping_timeout_seconds"] == 1.0


def test_task_queue_status_keeps_submission_ready_when_worker_ping_has_no_nodes(monkeypatch) -> None:
    fake_app = object()
    monkeypatch.setattr(status_task_queue, "_task_export_status", lambda: _export_status(fake_app))

    status = status_task_queue.task_queue_status(
        SimpleNamespace(redis_url="redis://localhost:6379/0", task_queue_worker_ping_timeout_seconds=0.2),
        redis_status={"ok": True},
        redact_url=lambda value: value,
        worker_ping_func=lambda app, timeout: {},
    )

    assert status["ready"] is True
    assert status["processing_ready"] is False
    assert status["worker_ping_checked"] is True
    assert status["worker_online"] is False
    assert status["worker_count"] == 0
    assert status["worker_ping_error"] is None
    assert status["worker_ping_timeout_seconds"] == 0.2


def test_task_queue_status_skips_worker_ping_when_broker_is_down(monkeypatch) -> None:
    fake_app = object()
    monkeypatch.setattr(status_task_queue, "_task_export_status", lambda: _export_status(fake_app))

    status = status_task_queue.task_queue_status(
        SimpleNamespace(redis_url="redis://localhost:6379/0"),
        redis_status={"ok": False, "error": "redis down"},
        redact_url=lambda value: value,
        worker_ping_func=lambda app, timeout: {"celery@worker-1": {"ok": "pong"}},
    )

    assert status["ready"] is False
    assert status["processing_ready"] is False
    assert status["worker_ping_checked"] is False
    assert status["worker_ping_skipped_reason"] == "broker_unavailable"
    assert status["worker_online"] is False


def _export_status(fake_app) -> dict:
    return {
        "task_export_namespace_available": True,
        "task_export_error": None,
        "exported_tasks_present": {name: True for name in status_task_queue.REQUIRED_TASK_EXPORTS},
        "missing_task_exports": [],
        "required_task_exports_present": True,
        "celery_app_available": True,
        "celery_app_main": "stock_ai",
        "task_names": dict(status_task_queue.EXPECTED_TASK_NAMES),
        "task_names_match_expected": True,
        "_celery_app": fake_app,
    }
