from __future__ import annotations

from app.ui import dashboard_core


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

    monkeypatch.setattr(dashboard_core.requests, "post", fake_post)

    assert dashboard_core.api_post("/ingest/manual", {"title": "x"}) == {"created": True}
    assert captured["url"].endswith("/ingest/manual")
    assert captured["json"] == {"title": "x"}
    assert captured["timeout"] == dashboard_core.API_WRITE_TIMEOUT_SECONDS


def test_api_task_post_uses_queue_timeout(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"task_id": "task-1"})

    monkeypatch.setattr(dashboard_core.requests, "post", fake_post)

    assert dashboard_core.api_task_post("/tasks/data-operation", {"operation": "market_refresh"}) == {
        "task_id": "task-1"
    }
    assert captured["url"].endswith("/tasks/data-operation")
    assert captured["timeout"] == dashboard_core.API_TASK_QUEUE_TIMEOUT_SECONDS
