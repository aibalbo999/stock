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
        "totals": {
            "run_count": 1,
            "success_count": 1,
            "failed_count": 0,
            "running_count": 0,
            "stale_running_count": 0,
        },
        "recent": [
            {
                "id": 16,
                "operation": "report_generation",
                "status": "success",
                "task_id": "task-success",
                "report_id": 15,
            }
        ],
    }


def _reports() -> list[dict]:
    return [
        {
            "id": 15,
            "title": "記憶體產業鏈 自動分析報告",
            "topic": "記憶體產業鏈",
            "generated_at": "2026-06-06T16:31:24",
        }
    ]


def _quota() -> dict:
    return {
        "recommended_model": "gemini-3.5-flash",
        "model_order": ["gemini-3.5-flash", "gemma-4-31b-it"],
        "models": [
            {
                "model": "gemini-3.5-flash",
                "status": "ready",
                "rank": 1,
                "routing_tier": "primary",
                "requests_remaining": 120,
                "request_budget": 250,
            },
            {
                "model": "gemma-4-31b-it",
                "status": "ready",
                "rank": 2,
                "routing_tier": "high_quota_fallback",
                "requests_remaining": 1000,
                "request_budget": 1000,
            }
        ],
    }


def _payload_validation_failure() -> dict:
    return {
        "task_id": "task-8150",
        "status": "failed",
        "operation": "follow_up_api",
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


def test_operator_status_overall_blocks_when_any_queue_readiness_flag_is_false() -> None:
    for task_queue in [
        {"ready": False, "processing_ready": True, "worker_online": True},
        {"ready": True, "processing_ready": False, "worker_online": True},
        {"ready": True, "processing_ready": True, "worker_online": False},
        {"ready": True, "worker_online": True},
    ]:
        assert operator_status_overall(
            {"task_queue": task_queue},
            _successful_task_summary(),
            _reports(),
        ) == {
            "state": "blocked",
            "label": "背景任務未就緒",
            "detail": "請先到系統設定檢查 Redis/Celery worker。",
        }


def test_operator_status_overall_blocks_for_stale_running_before_failures_or_reports() -> None:
    task_summary = _successful_task_summary()
    task_summary["totals"]["stale_running_count"] = 1
    task_summary["recent"].append(_payload_validation_failure())

    assert operator_status_overall(_healthy_service_snapshot(), task_summary, []) == {
        "state": "blocked",
        "label": "有卡住任務",
        "detail": "有任務疑似卡住，請先到維護頁處理。",
    }


def test_operator_status_overall_returns_attention_for_historical_failed_task() -> None:
    task_summary = _successful_task_summary()
    task_summary["totals"] = {
        "run_count": 2,
        "success_count": 1,
        "failed_count": 1,
        "running_count": 0,
        "stale_running_count": 0,
    }
    task_summary["recent"].append(
        {
            "task_id": "task-old-failure",
            "status": "failed",
            "operation": "report_generation",
            "retryable": False,
            "error_category": "runtime_storage",
        }
    )

    overall = operator_status_overall(_healthy_service_snapshot(), task_summary, _reports())

    assert overall["state"] == "attention"
    assert overall["label"] == "有待處理紀錄"
    assert "最近任務可執行" in overall["detail"]


def test_operator_status_cards_include_queue_report_quota_and_failure_actions() -> None:
    task_summary = _successful_task_summary()
    task_summary["recent"].append(_payload_validation_failure())

    cards = operator_status_cards(
        _healthy_service_snapshot(),
        task_summary,
        _quota(),
        _reports(),
    )

    assert cards == [
        {
            "title": "系統狀態",
            "value": "可送任務",
            "caption": "Worker 線上",
            "state": "ready",
            "action_label": "開始使用",
            "route_hint": "analysis",
        },
        {
            "title": "最新版報告",
            "value": "#15",
            "caption": "記憶體產業鏈",
            "state": "ready",
            "action_label": "讀報告",
            "route_hint": "report:15",
        },
        {
            "title": "AI 額度",
            "value": "gemini-3.5-flash",
            "caption": (
                "120 / 250｜順序：gemini-3.5-flash → gemma-4-31b-it｜"
                "受限：無｜高額度保底：gemma-4-31b-it"
            ),
            "state": "ready",
            "action_label": "查看額度",
            "route_hint": "settings:ai_quota",
        },
        {
            "title": "待處理事項",
            "value": "輸入或白名單已擋下任務",
            "caption": "補強或重跑任務曾被 payload 驗證擋下；修正後可重試。",
            "state": "attention",
            "action_label": "可重試",
            "route_hint": "task:task-8150",
        },
    ]


def test_quota_operator_summary_returns_recommendation_budget_ready_and_fallback_caption() -> None:
    assert quota_operator_summary(_quota()) == {
        "recommended_model": "gemini-3.5-flash",
        "remaining": "120 / 250",
        "state": "ready",
        "model_order_label": "順序：gemini-3.5-flash → gemma-4-31b-it",
        "limited_model_label": "受限：無",
        "high_quota_fallback_label": "高額度保底：gemma-4-31b-it",
        "caption": "順序：gemini-3.5-flash → gemma-4-31b-it｜受限：無｜高額度保底：gemma-4-31b-it",
    }


def test_quota_operator_summary_uses_exact_caption_when_no_high_quota_fallback() -> None:
    quota = _quota()
    quota["models"] = [quota["models"][0]]

    result = quota_operator_summary(quota)

    assert result["high_quota_fallback_label"] == "無高額度保底模型"
    assert result["caption"] == "順序：gemini-3.5-flash → gemma-4-31b-it｜受限：無｜無高額度保底模型"


def test_quota_operator_summary_surfaces_model_order_and_first_exhausted_model() -> None:
    quota = {
        "recommended_model": "gemini-2.5-flash",
        "model_order": [
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemma-4-31b-it",
        ],
        "models": [
            {
                "model": "gemini-3.5-flash",
                "status": "exhausted",
                "rank": 1,
                "requests_remaining": 0,
                "request_budget": 1500,
            },
            {
                "model": "gemini-2.5-flash",
                "status": "available",
                "rank": 2,
                "requests_remaining": 1490,
                "request_budget": 1500,
            },
            {
                "model": "gemini-2.5-flash-lite",
                "status": "cooldown",
                "rank": 3,
                "active_cooldown_seconds": 180,
                "requests_remaining": 1500,
                "request_budget": 1500,
            },
            {
                "model": "gemma-4-31b-it",
                "status": "available",
                "rank": 4,
                "routing_tier": "high_quota_fallback",
                "requests_remaining": 14400,
                "request_budget": 14400,
            },
        ],
    }

    result = quota_operator_summary(quota)

    assert result["recommended_model"] == "gemini-2.5-flash"
    assert result["remaining"] == "1490 / 1500"
    assert result["state"] == "ready"
    assert result["model_order_label"] == (
        "順序：gemini-3.5-flash → gemini-2.5-flash → "
        "gemini-2.5-flash-lite → gemma-4-31b-it"
    )
    assert result["limited_model_label"] == "受限：gemini-3.5-flash（耗盡）"
    assert result["high_quota_fallback_label"] == "高額度保底：gemma-4-31b-it"


def test_quota_operator_summary_surfaces_first_cooldown_model_when_no_exhausted() -> None:
    quota = {
        "recommended_model": "gemini-2.5-flash",
        "model_order": ["gemini-3.5-flash", "gemini-2.5-flash"],
        "models": [
            {
                "model": "gemini-3.5-flash",
                "status": "cooldown",
                "rank": 1,
                "active_cooldown_seconds": 90,
                "requests_remaining": 1500,
                "request_budget": 1500,
            },
            {
                "model": "gemini-2.5-flash",
                "status": "available",
                "rank": 2,
                "requests_remaining": 1490,
                "request_budget": 1500,
            },
        ],
    }

    assert quota_operator_summary(quota)["limited_model_label"] == (
        "受限：gemini-3.5-flash（冷卻 90 秒）"
    )


def test_quota_operator_summary_marks_untracked_when_recommended_model_missing() -> None:
    quota = _quota()
    quota["recommended_model"] = "missing-model"

    result = quota_operator_summary(quota)

    assert result["recommended_model"] == "missing-model"
    assert result["remaining"] == "額度未追蹤"
    assert result["state"] == "attention"


def test_quota_operator_summary_marks_untracked_when_request_budget_or_remaining_missing() -> None:
    for model_patch in [
        {"requests_remaining": 5, "request_budget": ""},
        {"requests_remaining": "", "request_budget": 250},
    ]:
        quota = _quota()
        quota["models"][0] = {**quota["models"][0], **model_patch}

        assert quota_operator_summary(quota)["remaining"] == "額度未追蹤"


def test_task_failure_action_summary_maps_payload_validation_retryable_failure() -> None:
    assert task_failure_action_summary(_payload_validation_failure()) == {
        "state": "attention",
        "label": "輸入或白名單已擋下任務",
        "detail": "補強或重跑任務曾被 payload 驗證擋下；修正後可重試。",
        "action_label": "可重試",
        "route_hint": "task:task-8150",
    }


def test_task_failure_action_summary_uses_fixed_payload_validation_label() -> None:
    failure = {**_payload_validation_failure(), "error_summary": "custom backend detail"}

    assert task_failure_action_summary(failure)["label"] == "輸入或白名單已擋下任務"
