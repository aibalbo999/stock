from __future__ import annotations

from app.ui import api_client, dashboard_core


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
    assert dashboard_core.api_post is api_client.api_post


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
    assert dashboard_core.api_task_post is api_client.api_task_post
