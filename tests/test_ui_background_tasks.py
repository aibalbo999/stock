from __future__ import annotations

from types import SimpleNamespace

import requests

from app.ui import background_tasks


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict = {}
        self.errors: list[str] = []
        self.successes: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def success(self, message: str) -> None:
        self.successes.append(message)


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
    assert fake_st.errors == ["股價刷新任務送出失敗：task queue unavailable 建議：啟動 Redis；啟動 Celery"]
    assert fake_st.successes == []


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
    )

    assert result == {"task_id": "task-data"}
    assert captured == {"operation": "market_refresh", "payload": {"tickers": ["2330"]}}
    assert fake_st.session_state["last_data_task_id"] == "task-data"
