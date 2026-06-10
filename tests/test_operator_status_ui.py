from __future__ import annotations

from app.ui.operator_status import (
    operator_status_cards,
    operator_status_overall,
    quota_operator_summary,
    task_failure_action_summary,
)


def _healthy_service_snapshot() -> dict:
    return {
        "task_queue": {
            "ready": True,
            "processing_ready": True,
            "worker_online": True,
        }
    }


def _successful_task_summary() -> dict:
    return {
        "recent": [
            {
                "id": 16,
                "operation": "report_generation",
                "status": "success",
                "task_id": "task-success",
                "report_id": 15,
            }
        ],
        "recent_failures": [],
    }


def _reports() -> list[dict]:
    return [{"id": 15, "topic": "AI 供應鏈", "created_at": "2026-06-10T08:00:00"}]


def _quota() -> dict:
    return {
        "recommended_model": "gemini-2.5-flash",
        "models": [
            {
                "model": "gemini-2.5-flash",
                "status": "ready",
                "requests_remaining": 120,
                "request_budget": 250,
            }
        ],
        "routing_policy": {"high_quota_fallback_models": ["gemma-4-31b-it"]},
    }


def _payload_validation_failure() -> dict:
    return {
        "task_id": "task-8150",
        "status": "failed",
        "operation": "report_generation",
        "retryable": True,
        "error_category": "payload_validation",
        "error_summary": "輸入或白名單已擋下任務",
    }


def test_operator_status_overall_returns_ready_when_queue_task_and_reports_ready() -> None:
    assert operator_status_overall(
        _healthy_service_snapshot(),
        _successful_task_summary(),
        _reports(),
    ) == {"state": "ready", "label": "可執行", "detail": "背景任務與最新版報告都可用。"}


def test_operator_status_overall_returns_attention_for_historical_failed_task() -> None:
    task_summary = _successful_task_summary()
    task_summary["recent_failures"] = [
        {
            "task_id": "task-old-failure",
            "status": "failed",
            "operation": "report_generation",
            "retryable": False,
            "error_category": "runtime_storage",
        }
    ]

    overall = operator_status_overall(_healthy_service_snapshot(), task_summary, _reports())

    assert overall["state"] == "attention"
    assert overall["label"] == "有待處理紀錄"
    assert "最近任務可執行" in overall["detail"]


def test_operator_status_cards_include_queue_report_quota_and_failure_actions() -> None:
    task_summary = _successful_task_summary()
    task_summary["recent_failures"] = [_payload_validation_failure()]

    cards = operator_status_cards(
        _healthy_service_snapshot(),
        task_summary,
        _quota(),
        _reports(),
    )

    assert [card["title"] for card in cards] == ["系統狀態", "最新版報告", "AI 額度", "待處理事項"]
    assert cards[0]["queue_state"] == "ready"
    assert cards[1]["report_id"] == "15"
    assert cards[1]["value"] == "#15"
    assert cards[2]["recommended_model"] == "gemini-2.5-flash"
    assert cards[2]["remaining"] == "120 / 250"
    assert cards[3]["failure_action"] == "可重試"
    assert cards[3]["route_hint"] == "task:task-8150"


def test_quota_operator_summary_returns_recommendation_budget_ready_and_fallback_caption() -> None:
    assert quota_operator_summary(_quota()) == {
        "recommended_model": "gemini-2.5-flash",
        "remaining": "120 / 250",
        "state": "ready",
        "caption": "高額度保底：gemma-4-31b-it",
    }


def test_task_failure_action_summary_maps_payload_validation_retryable_failure() -> None:
    assert task_failure_action_summary(_payload_validation_failure()) == {
        "state": "attention",
        "label": "輸入或白名單已擋下任務",
        "detail": "補強或重跑任務曾被 payload 驗證擋下；修正後可重試。",
        "action_label": "可重試",
        "route_hint": "task:task-8150",
    }
