from __future__ import annotations

import requests

from app.ui import api_client


class FakeResponse:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {"ok": True}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_api_post_uses_short_write_timeout(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"created": True})

    monkeypatch.setattr(api_client.requests, "post", fake_post)

    assert api_client.api_post("/ingest/manual", {"title": "x"}) == {"created": True}
    assert captured["url"].endswith("/ingest/manual")
    assert captured["json"] == {"title": "x"}
    assert captured["timeout"] == api_client.API_WRITE_TIMEOUT_SECONDS


def test_api_task_post_uses_queue_timeout(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"task_id": "task-1"})

    monkeypatch.setattr(api_client.requests, "post", fake_post)

    assert api_client.api_task_post("/tasks/data-operation", {"operation": "market_refresh"}) == {
        "task_id": "task-1"
    }
    assert captured["url"].endswith("/tasks/data-operation")
    assert captured["timeout"] == api_client.API_TASK_QUEUE_TIMEOUT_SECONDS


def test_api_task_queue_status_uses_short_preflight_timeout(monkeypatch) -> None:
    captured = {}

    def fake_get(url, timeout):
        captured.update({"url": url, "timeout": timeout})
        return FakeResponse({"task_queue": {"ready": True, "broker_ok": True}})

    monkeypatch.setattr(api_client.requests, "get", fake_get)

    assert api_client.api_task_queue_status() == {"ready": True, "broker_ok": True}
    assert captured["url"].endswith("/services/status")
    assert captured["timeout"] == api_client.API_TASK_PREFLIGHT_TIMEOUT_SECONDS


def test_request_error_message_formats_structured_task_submission_500() -> None:
    response = FakeResponse(
        {
            "detail": {
                "code": "background_task_submission_failed",
                "message": "背景任務送出時發生未預期錯誤。",
                "operation": "market_refresh",
                "retryable": False,
                "error_type": "RuntimeError",
                "next_steps": ["查看 API log。", "確認 Celery task 匯出。"],
            }
        }
    )
    exc = requests.HTTPError("500 Server Error")
    exc.response = response

    assert api_client.request_error_message(exc) == (
        "背景任務送出時發生未預期錯誤。 建議：查看 API log。；確認 Celery task 匯出。"
    )
