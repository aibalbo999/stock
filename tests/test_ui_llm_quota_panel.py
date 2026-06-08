from __future__ import annotations

from app.ui.llm_quota_panel import (
    llm_quota_captions,
    llm_quota_metric_values,
    llm_quota_model_rows,
)
from app.ui.maintenance_ai_panels import (
    llm_usage_metric_values,
    llm_usage_recent_routing_rows,
    llm_usage_routing_captions,
    llm_usage_routing_rows,
)


def test_llm_quota_metric_values_show_recommendation_usage_and_reset() -> None:
    metrics = llm_quota_metric_values(
        {
            "recommended_model": "gemini-2.5-flash",
            "totals": {"request_count": 7, "total_token_estimate": 1234},
            "window": {"end": "2026-06-07T23:59:59.999999-07:00"},
        }
    )

    assert metrics == {
        "推薦模型": "gemini-2.5-flash",
        "今日請求": 7,
        "今日 Token": 1234,
        "額度重置": "06-07 23:59 UTC-07:00",
    }


def test_llm_quota_model_rows_include_routing_and_failure_context() -> None:
    rows = llm_quota_model_rows(
        {
            "models": [
                {
                    "rank": 1,
                    "model": "gemini-3.5-flash",
                    "status": "exhausted",
                    "routing_tier": "primary",
                    "status_reason": "request_budget_exhausted",
                    "routing_reason": "Skipped until the next quota window.",
                    "requests_used": 250,
                    "request_budget": 250,
                    "requests_remaining": 0,
                    "tokens_used": 1000,
                    "token_budget": None,
                    "tokens_remaining": None,
                    "fallback_count": 0,
                    "retryable_failure_count": 3,
                }
            ]
        }
    )

    assert rows == [
        {
            "rank": 1,
            "model": "gemini-3.5-flash",
            "status": "exhausted",
            "tier": "primary",
            "reason": "request_budget_exhausted",
            "routing_reason": "Skipped until the next quota window.",
            "requests_used": 250,
            "request_budget": 250,
            "requests_remaining": 0,
            "tokens_used": 1000,
            "token_budget": None,
            "tokens_remaining": None,
            "fallback_count": 0,
            "retryable_failure_count": 3,
        }
    ]


def test_llm_quota_captions_summarize_recommendation_budget_note_and_gemma_fallback() -> None:
    captions = llm_quota_captions(
        {
            "recommended_model": "gemini-2.5-flash",
            "recommended_rank": 2,
            "recommended_routing_tier": "fallback",
            "recommended_reason": "Earlier model(s) exhausted.",
            "window": {"reset_in_seconds": 5400},
            "budget_source": {"note": "Limits are project-level."},
            "routing_policy": {"high_quota_fallback_models": ["gemma-4-31b-it"]},
        }
    )

    assert captions == [
        "目前推薦：gemini-2.5-flash｜順位 2｜tier=fallback｜約 1 小時 30 分鐘 後重置",
        "Earlier model(s) exhausted.",
        "Limits are project-level.",
        "高額度保底模型：gemma-4-31b-it",
    ]


def test_llm_usage_routing_helpers_show_recommendation_and_model_order() -> None:
    summary = {
        "totals": {
            "request_count": 7,
            "total_token_estimate": 1234,
            "estimated_cost_usd": 0.0123,
            "fallback_path_count": 2,
            "retryable_failure_count": 4,
            "quota_skip_count": 3,
            "degraded_from_primary_count": 1,
        },
        "routing_snapshot": {
            "available": True,
            "recommended_model": "gemini-2.5-flash",
            "recommended_rank": 2,
            "recommended_routing_tier": "fallback",
            "recommended_reason": "Earlier model(s) exhausted.",
            "high_quota_fallback_models": ["gemma-4-31b-it"],
            "models": [
                {
                    "rank": 1,
                    "model": "gemini-3.5-flash",
                    "status": "exhausted",
                    "status_reason": "request_budget_exhausted",
                    "routing_tier": "primary",
                    "requests_used": 250,
                    "request_budget": 250,
                    "requests_remaining": 0,
                    "completion_count": 249,
                    "tokens_used": 1000,
                    "token_budget": None,
                    "tokens_remaining": None,
                },
                {
                    "rank": 2,
                    "model": "gemini-2.5-flash",
                    "status": "available",
                    "status_reason": "within_configured_budget",
                    "routing_tier": "fallback",
                    "requests_used": 3,
                    "request_budget": 250,
                    "requests_remaining": 247,
                    "completion_count": 3,
                    "tokens_used": 120,
                    "token_budget": None,
                    "tokens_remaining": None,
                },
            ],
        }
    }

    assert llm_usage_metric_values(summary) == {
        "7 日請求": 7,
        "7 日 Token": 1234,
        "估算成本 USD": "0.0123",
        "Fallback 次數": 2,
        "可重試失敗": 4,
        "Quota skip": 3,
        "模型降級": 1,
    }
    assert llm_usage_routing_captions(summary) == [
        "目前推薦：gemini-2.5-flash｜順位 2｜tier=fallback",
        "Earlier model(s) exhausted.",
        "高額度保底模型：gemma-4-31b-it",
    ]
    assert llm_usage_routing_rows(summary) == [
        {
            "rank": 1,
            "model": "gemini-3.5-flash",
            "status": "exhausted",
            "tier": "primary",
            "reason": "request_budget_exhausted",
            "requests_used": 250,
            "request_budget": 250,
            "requests_remaining": 0,
            "completion_count": 249,
            "tokens_used": 1000,
            "token_budget": None,
            "tokens_remaining": None,
        },
        {
            "rank": 2,
            "model": "gemini-2.5-flash",
            "status": "available",
            "tier": "fallback",
            "reason": "within_configured_budget",
            "requests_used": 3,
            "request_budget": 250,
            "requests_remaining": 247,
            "completion_count": 3,
            "tokens_used": 120,
            "token_budget": None,
            "tokens_remaining": None,
        },
    ]


def test_llm_usage_recent_routing_rows_surface_quota_degrade_events() -> None:
    assert llm_usage_recent_routing_rows(
        {
            "recent": [
                {
                    "created_at": "2026-06-09T08:00:00",
                    "operation": "report_generation",
                    "model": "gemma-4-31b-it",
                    "selected_model_rank": 4,
                    "selected_routing_tier": "high_quota_fallback",
                    "routing_reason": "quota_or_cooldown_skip",
                    "quota_skip_count": 2,
                    "daily_quota_skip_count": 1,
                    "cooldown_skip_count": 1,
                    "degraded_from_primary": True,
                },
                {
                    "created_at": "2026-06-09T08:05:00",
                    "operation": "health_check",
                    "model": "gemini-3.5-flash",
                    "quota_skip_count": 0,
                    "degraded_from_primary": False,
                },
                "ignored",
            ]
        }
    ) == [
        {
            "created_at": "2026-06-09T08:00:00",
            "operation": "report_generation",
            "model": "gemma-4-31b-it",
            "selected_rank": 4,
            "tier": "high_quota_fallback",
            "routing_reason": "quota_or_cooldown_skip",
            "quota_skip_count": 2,
            "daily_quota_skip_count": 1,
            "cooldown_skip_count": 1,
            "degraded_from_primary": True,
        }
    ]


def test_llm_usage_routing_captions_show_unavailable_reason() -> None:
    assert llm_usage_routing_captions(
        {"routing_snapshot": {"available": False, "reason": "usage_store_unavailable"}}
    ) == ["模型路由實況尚不可用：usage_store_unavailable"]
    assert llm_usage_routing_rows({}) == []
    assert llm_usage_metric_values({}) == {
        "7 日請求": 0,
        "7 日 Token": 0,
        "估算成本 USD": "0.0000",
        "Fallback 次數": 0,
        "可重試失敗": 0,
        "Quota skip": 0,
        "模型降級": 0,
    }
    assert llm_usage_recent_routing_rows({}) == []
