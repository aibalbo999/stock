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
                    "risk_level": "exhausted",
                    "routing_tier": "primary",
                    "status_reason": "request_budget_exhausted",
                    "routing_reason": "Skipped until the next quota window.",
                    "requests_used": 250,
                    "request_budget": 250,
                    "free_tier_request_budget_reference": None,
                    "quota_reference_source": "project_configured_ai_studio_limit",
                    "requests_remaining": 0,
                    "request_used_ratio": 1.0,
                    "tokens_used": 1000,
                    "token_budget": None,
                    "tokens_remaining": None,
                    "token_used_ratio": None,
                    "fallback_count": 0,
                    "retryable_failure_count": 3,
                    "quota_hit_count": 2,
                    "quota_skip_count": 1,
                    "daily_quota_skip_count": 0,
                    "cooldown_skip_count": 1,
                    "active_cooldown_seconds": 1800,
                    "last_quota_hit_at": "2026-06-07T11:40:00",
                    "next_action": "No action needed for routing.",
                }
            ]
        }
    )

    assert rows == [
        {
            "順位": 1,
            "模型": "gemini-3.5-flash",
            "狀態": "額度用完",
            "風險": "額度用完",
            "路由層級": "主力模型",
            "狀態原因": "請求額度已用完",
            "路由原因": "跳過到下一個額度週期。",
            "今日請求": "250 / 250",
            "Free Tier 參考": "-",
            "額度來源": "專案設定的 AI Studio 限制",
            "剩餘請求": 0,
            "請求用量": "100.0%",
            "今日 Token": "1000 / -",
            "剩餘 Token": "-",
            "Token 用量": "-",
            "後援次數": 0,
            "可重試失敗": 3,
            "額度命中": 2,
            "額度略過": 1,
            "日額度略過": 0,
            "冷卻略過": 1,
            "冷卻剩餘": "30 分鐘",
            "最近額度命中": "2026-06-07T11:40:00",
            "下一步": "路由會自動降級，不需手動操作。",
        }
    ]
    rendered = str(rows)
    assert "status" not in rendered
    assert "routing_tier" not in rendered
    assert "request_budget_exhausted" not in rendered
    assert "Skipped until the next quota window." not in rendered


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


def test_llm_quota_captions_surface_free_tier_reference_drift() -> None:
    captions = llm_quota_captions(
        {
            "recommended_model": "gemini-3.5-flash",
            "recommended_rank": 1,
            "recommended_routing_tier": "primary",
            "models": [
                {
                    "model": "gemini-2.5-flash-lite",
                    "request_budget": 250,
                    "free_tier_request_budget_reference": 1000,
                }
            ],
        }
    )

    assert captions == [
        "目前推薦：gemini-3.5-flash｜順位 1｜tier=primary",
        (
            "Free Tier 參考差異：gemini-2.5-flash-lite: configured 250 / official 1000。"
            "實際仍以 Google AI Studio project limit 為準。"
        ),
    ]


def test_llm_quota_captions_surface_near_limit_alerts_without_changing_recommendation() -> None:
    captions = llm_quota_captions(
        {
            "recommended_model": "gemini-3.5-flash",
            "recommended_rank": 1,
            "recommended_routing_tier": "primary",
            "recommended_reason": (
                "Top-ranked configured model still has remaining tracked quota; "
                "it has reached the 80% warning threshold."
            ),
            "window": {"reset_in_seconds": 600},
            "alerts": [
                {
                    "model": "gemini-3.5-flash",
                    "severity": "warning",
                    "usage_ratio": 0.8,
                    "next_action": "Keep using this model until exhausted.",
                }
            ],
        }
    )

    assert captions == [
        "目前推薦：gemini-3.5-flash｜順位 1｜tier=primary｜約 10 分鐘 後重置",
        (
            "Top-ranked configured model still has remaining tracked quota; "
            "it has reached the 80% warning threshold."
        ),
        "額度提醒：gemini-3.5-flash warning（已用 80.0%）；Keep using this model until exhausted.",
    ]


def test_llm_quota_captions_surface_active_cooldown_alerts() -> None:
    captions = llm_quota_captions(
        {
            "recommended_model": "gemini-2.5-flash",
            "recommended_rank": 2,
            "recommended_routing_tier": "fallback",
            "window": {"reset_in_seconds": 600},
            "alerts": [
                {
                    "model": "gemini-3.5-flash",
                    "severity": "warning",
                    "active_cooldown_seconds": 1800,
                    "next_action": "No manual action needed.",
                }
            ],
        }
    )

    assert captions == [
        "目前推薦：gemini-2.5-flash｜順位 2｜tier=fallback｜約 10 分鐘 後重置",
        "額度提醒：gemini-3.5-flash warning；cooldown 約 30 分鐘；No manual action needed.",
    ]


def test_llm_usage_routing_helpers_show_recommendation_and_model_order() -> None:
    summary = {
        "totals": {
            "request_count": 7,
            "total_token_estimate": 1234,
            "estimated_cost_usd": 0.0123,
            "p95_latency_ms": 456.78,
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
        "P95 LLM 延遲 ms": 456.78,
        "後援次數": 2,
        "可重試失敗": 4,
        "額度略過": 3,
        "模型降級": 1,
    }
    assert llm_usage_routing_captions(summary) == [
        "目前推薦：gemini-2.5-flash｜順位 2｜路由層級 後援模型",
        "前序模型額度已用完，已自動改用下一順位。",
        "高額度保底模型：gemma-4-31b-it",
    ]
    assert llm_usage_routing_rows(summary) == [
        {
            "順位": 1,
            "模型": "gemini-3.5-flash",
            "狀態": "額度用完",
            "路由層級": "主力模型",
            "狀態原因": "請求額度已用完",
            "今日請求": "250 / 250",
            "剩餘請求": 0,
            "完成次數": 249,
            "今日 Token": "1000 / -",
            "剩餘 Token": "-",
        },
        {
            "順位": 2,
            "模型": "gemini-2.5-flash",
            "狀態": "可用",
            "路由層級": "後援模型",
            "狀態原因": "仍在設定額度內",
            "今日請求": "3 / 250",
            "剩餘請求": 247,
            "完成次數": 3,
            "今日 Token": "120 / -",
            "剩餘 Token": "-",
        },
    ]
    rendered = str(llm_usage_routing_rows(summary))
    assert "status" not in rendered
    assert "routing_tier" not in rendered
    assert "request_budget_exhausted" not in rendered
    assert "tier=fallback" not in str(llm_usage_routing_captions(summary))
    assert "Earlier model(s) exhausted." not in str(llm_usage_routing_captions(summary))


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
            "時間": "2026-06-09T08:00:00",
            "任務": "報告生成",
            "模型": "gemma-4-31b-it",
            "選中順位": 4,
            "路由層級": "高額度保底",
            "路由原因": "額度或冷卻略過",
            "額度略過": 2,
            "日額度略過": 1,
            "冷卻略過": 1,
            "已降級": "是",
        }
    ]


def test_llm_usage_routing_captions_show_unavailable_reason() -> None:
    assert llm_usage_routing_captions(
        {"routing_snapshot": {"available": False, "reason": "usage_store_unavailable"}}
    ) == ["模型路由實況尚不可用：用量資料庫暫時不可用"]
    assert llm_usage_routing_rows({}) == []
    assert llm_usage_metric_values({}) == {
        "7 日請求": 0,
        "7 日 Token": 0,
        "估算成本 USD": "0.0000",
        "P95 LLM 延遲 ms": "-",
        "後援次數": 0,
        "可重試失敗": 0,
        "額度略過": 0,
        "模型降級": 0,
    }
    assert llm_usage_recent_routing_rows({}) == []
