from __future__ import annotations

from types import SimpleNamespace

import requests

from app.ui import background_tasks


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict = {}
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def success(self, message: str) -> None:
        self.successes.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def test_submit_background_task_stores_task_id_and_clears_status_cache(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    fake_st.session_state.update(
        {
            "refresh_data_task_status_status": {"task_id": "old"},
            "refresh_manual_data_task_status_status": {"task_id": "old"},
            "unrelated": "keep",
        }
    )
    monkeypatch.setattr(background_tasks, "st", fake_st)

    result = background_tasks.submit_background_task(
        lambda: {"task_id": "task-new", "status": "queued"},
        task_state_key="last_data_task_id",
        status_state_keys=(
            "refresh_data_task_status_status",
            "refresh_manual_data_task_status_status",
        ),
        success_message="已送出股價刷新背景任務",
        error_message="股價刷新任務送出失敗",
    )

    assert result == {"task_id": "task-new", "status": "queued"}
    assert fake_st.session_state["last_data_task_id"] == "task-new"
    assert fake_st.session_state["unrelated"] == "keep"
    assert "refresh_data_task_status_status" not in fake_st.session_state
    assert "refresh_manual_data_task_status_status" not in fake_st.session_state
    assert fake_st.successes == ["已送出股價刷新背景任務：task-new"]
    assert fake_st.errors == []
    assert fake_st.warnings == []


def test_submit_background_task_preserves_state_on_request_error(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    fake_st.session_state["last_data_task_id"] = "task-old"
    monkeypatch.setattr(background_tasks, "st", fake_st)

    response = SimpleNamespace(
        json=lambda: {
            "detail": {
                "message": "task queue unavailable",
                "next_steps": ["啟動 Redis", "啟動 Celery"],
            }
        }
    )
    exc = requests.HTTPError("500 Server Error")
    exc.response = response

    result = background_tasks.submit_background_task(
        lambda: (_ for _ in ()).throw(exc),
        task_state_key="last_data_task_id",
        status_state_keys=("refresh_data_task_status_status",),
        success_message="已送出股價刷新背景任務",
        error_message="股價刷新任務送出失敗",
    )

    assert result is None
    assert fake_st.session_state["last_data_task_id"] == "task-old"
    assert fake_st.errors == [
        "股價刷新任務送出失敗：task queue unavailable 建議：啟動 Redis；啟動 Celery"
    ]
    assert fake_st.successes == []
    assert fake_st.warnings == []


def test_submit_background_task_preserves_state_on_json_error(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    fake_st.session_state["last_data_task_id"] = "task-old"
    monkeypatch.setattr(background_tasks, "st", fake_st)

    result = background_tasks.submit_background_task(
        lambda: (_ for _ in ()).throw(ValueError("invalid json")),
        task_state_key="last_data_task_id",
        status_state_keys=("refresh_data_task_status_status",),
        success_message="已送出股價刷新背景任務",
        error_message="股價刷新任務送出失敗",
    )

    assert result is None
    assert fake_st.session_state["last_data_task_id"] == "task-old"
    assert fake_st.errors == ["股價刷新任務送出失敗：invalid json"]
    assert fake_st.successes == []
    assert fake_st.warnings == []


def test_submit_background_task_rejects_response_without_task_id(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(background_tasks, "st", fake_st)

    result = background_tasks.submit_background_task(
        lambda: {"status": "queued"},
        task_state_key="last_async_task_id",
        success_message="已送出分析背景任務",
        error_message="分析背景任務送出失敗",
    )

    assert result is None
    assert "last_async_task_id" not in fake_st.session_state
    assert fake_st.errors == ["分析背景任務送出失敗：API 回傳缺少 task_id。"]


def test_submit_data_operation_task_delegates_to_data_operation_api(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    captured = {}
    monkeypatch.setattr(background_tasks, "st", fake_st)

    def fake_queue_data_operation(operation: str, payload: dict) -> dict:
        captured["operation"] = operation
        captured["payload"] = payload
        return {"task_id": "task-data"}

    monkeypatch.setattr(background_tasks, "queue_data_operation", fake_queue_data_operation)

    result = background_tasks.submit_data_operation_task(
        "market_refresh",
        {"tickers": ["2330"]},
        status_state_keys=("refresh_data_task_status_status",),
        success_message="已送出股價刷新背景任務",
        error_message="股價刷新任務送出失敗",
        preflight=False,
    )

    assert result == {"task_id": "task-data"}
    assert captured == {"operation": "market_refresh", "payload": {"tickers": ["2330"]}}
    assert fake_st.session_state["last_data_task_id"] == "task-data"


def test_submit_background_task_preflight_blocks_unready_queue(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    called = {"submit": False}
    monkeypatch.setattr(background_tasks, "st", fake_st)
    monkeypatch.setattr(
        background_tasks,
        "api_task_queue_status",
        lambda: {
            "ready": False,
            "broker_configured": True,
            "broker_ok": False,
            "backend_ok": False,
            "submission_contract_ready": True,
            "celery_app_available": True,
            "missing_task_exports": [],
            "task_names_match_expected": True,
            "smoke_commands": [
                ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping"
            ],
        },
    )

    def submitter() -> dict:
        called["submit"] = True
        return {"task_id": "task-should-not-submit"}

    result = background_tasks.submit_background_task(
        submitter,
        task_state_key="last_data_task_id",
        success_message="已送出股價刷新背景任務",
        error_message="股價刷新任務送出失敗",
        preflight=True,
    )

    assert result is None
    assert called["submit"] is False
    assert "last_data_task_id" not in fake_st.session_state
    assert fake_st.errors == [
        "股價刷新任務送出失敗：Redis broker/backend 未連線。 "
        "可用指令：.venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping"
    ]
    assert fake_st.successes == []


def test_submit_background_task_warns_and_continues_when_preflight_status_unavailable(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(background_tasks, "st", fake_st)
    monkeypatch.setattr(
        background_tasks,
        "api_task_queue_status",
        lambda: (_ for _ in ()).throw(requests.ConnectionError("status endpoint down")),
    )

    result = background_tasks.submit_background_task(
        lambda: {"task_id": "task-after-warning"},
        task_state_key="last_data_task_id",
        success_message="已送出股價刷新背景任務",
        error_message="股價刷新任務送出失敗",
        preflight=True,
    )

    assert result == {"task_id": "task-after-warning"}
    assert fake_st.session_state["last_data_task_id"] == "task-after-warning"
    assert fake_st.warnings == ["無法預先確認背景任務狀態：status endpoint down；仍會嘗試送出。"]
    assert fake_st.successes == ["已送出股價刷新背景任務：task-after-warning"]


def test_submit_background_task_warns_but_submits_when_worker_is_offline(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(background_tasks, "st", fake_st)
    monkeypatch.setattr(
        background_tasks,
        "api_task_queue_status",
        lambda: {
            "ready": True,
            "worker_ping_checked": True,
            "worker_online": False,
            "worker_ping_error": None,
            "smoke_commands": [
                ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping"
            ],
        },
    )

    result = background_tasks.submit_background_task(
        lambda: {"task_id": "task-queued-without-worker"},
        task_state_key="last_data_task_id",
        success_message="已送出股價刷新背景任務",
        error_message="股價刷新任務送出失敗",
        preflight=True,
    )

    assert result == {"task_id": "task-queued-without-worker"}
    assert fake_st.session_state["last_data_task_id"] == "task-queued-without-worker"
    assert fake_st.warnings == [
        "背景任務 queue 可送出，但 Celery worker 未回應，任務可能會排隊等待。 "
        "可用指令：.venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping"
    ]
    assert fake_st.successes == ["已送出股價刷新背景任務：task-queued-without-worker"]


def test_task_queue_preflight_reuses_ready_status_cache(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    calls = {"status": 0}
    clock = {"now": 100.0}
    monkeypatch.setattr(background_tasks, "st", fake_st)
    monkeypatch.setattr(background_tasks, "monotonic", lambda: clock["now"])

    def fake_status() -> dict:
        calls["status"] += 1
        return {"ready": True, "worker_ping_checked": False}

    monkeypatch.setattr(background_tasks, "api_task_queue_status", fake_status)

    assert background_tasks.task_queue_preflight_ready(error_message="任務送出失敗") is True
    assert background_tasks.task_queue_preflight_ready(error_message="任務送出失敗") is True

    assert calls["status"] == 1
    assert fake_st.errors == []
    assert fake_st.warnings == []


def test_task_queue_preflight_refreshes_after_cache_ttl(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    calls = {"status": 0}
    clock = {"now": 100.0}
    monkeypatch.setattr(background_tasks, "st", fake_st)
    monkeypatch.setattr(background_tasks, "monotonic", lambda: clock["now"])

    def fake_status() -> dict:
        calls["status"] += 1
        return {"ready": True, "worker_ping_checked": False}

    monkeypatch.setattr(background_tasks, "api_task_queue_status", fake_status)

    assert background_tasks.task_queue_preflight_ready(error_message="任務送出失敗") is True
    clock["now"] += background_tasks.TASK_QUEUE_PREFLIGHT_READY_TTL_SECONDS + 0.1
    assert background_tasks.task_queue_preflight_ready(error_message="任務送出失敗") is True

    assert calls["status"] == 2
