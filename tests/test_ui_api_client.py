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


def test_request_error_message_includes_data_operation_context() -> None:
    response = FakeResponse(
        {
            "detail": {
                "code": "background_task_submission_failed",
                "message": "背景任務送出時發生未預期錯誤。",
                "operation": "market_refresh",
                "context": {
                    "failure_stage": "task_submission",
                    "operation": "market_refresh",
                    "tickers": ["2330", "2382"],
                    "ticker_count": 2,
                    "start_date": "2026-05-01",
                    "end_date": "2026-06-08",
                    "provider_hint": "FinMind / Fugle / TWSE fallback",
                },
                "next_steps": ["查看 API log。"],
            }
        }
    )
    exc = requests.HTTPError("500 Server Error")
    exc.response = response

    assert api_client.request_error_message(exc) == (
        "背景任務送出時發生未預期錯誤。 "
        "診斷：操作：市場資料刷新；股票：2330, 2382（2 檔）；"
        "期間：2026-05-01 至 2026-06-08；"
        "資料源：FinMind / Fugle / TWSE fallback；階段：任務送出 "
        "建議：查看 API log。"
    )


def test_request_error_message_includes_submission_failure_category() -> None:
    response = FakeResponse(
        {
            "detail": {
                "code": "background_task_submission_failed",
                "message": "背景任務送出時發生未預期錯誤。",
                "operation": "market_refresh",
                "error_category": "task_queue",
                "error_severity": "error",
                "error_summary": "Redis/Celery queue 或 worker 異常",
                "context": {
                    "failure_stage": "task_submission",
                    "operation": "market_refresh",
                    "tickers": ["2330"],
                    "ticker_count": 1,
                },
                "next_steps": ["確認 /services/status 的 task_queue.ready。"],
            }
        }
    )
    exc = requests.HTTPError("500 Server Error")
    exc.response = response

    message = api_client.request_error_message(exc)

    assert message == (
        "背景任務送出時發生未預期錯誤。 "
        "狀況：Redis/Celery queue 或 worker 異常 "
        "診斷：操作：市場資料刷新；股票：2330（1 檔）；階段：任務送出 "
        "建議：到系統設定 > 維護 > 背景任務觀測確認 Redis/Celery 與 worker。；"
        "修復後重新送出任務。"
    )
    assert "task_queue/error" not in message
    assert "market_refresh" not in message
    assert "task_submission" not in message
    assert "/services/status" not in message
