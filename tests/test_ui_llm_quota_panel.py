from __future__ import annotations

from app.ui.llm_quota_panel import (
    llm_quota_captions,
    llm_quota_metric_values,
    llm_quota_model_rows,
)
from app.ui.maintenance_ai_panels import (
    llm_usage_alert_rows,
    llm_usage_cost_budget_caption,
    llm_usage_daily_rows,
    llm_usage_metric_values,
    llm_usage_model_rows,
    llm_usage_operation_rows,
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
        "目前推薦：gemini-2.5-flash｜順位 2｜路由層級 後援模型｜約 1 小時 30 分鐘 後重置",
        "前序模型額度已用完，已自動改用下一順位。",
        "額度限制以專案層級為準。",
        "高額度保底模型：gemma-4-31b-it",
    ]
    rendered = str(captions)
    assert "tier=fallback" not in rendered
    assert "Earlier model(s) exhausted." not in rendered
    assert "Limits are project-level." not in rendered


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
        "目前推薦：gemini-3.5-flash｜順位 1｜路由層級 主力模型",
        (
            "Free Tier 參考差異：gemini-2.5-flash-lite 設定 250 / 官方 1000。"
            "實際仍以 Google AI Studio 專案額度為準。"
        ),
    ]
    rendered = str(captions)
    assert "tier=primary" not in rendered
    assert "configured" not in rendered
    assert "official" not in rendered
    assert "project limit" not in rendered


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
        "目前推薦：gemini-3.5-flash｜順位 1｜路由層級 主力模型｜約 10 分鐘 後重置",
        "最高順位模型仍有追蹤額度，已接近 80% 提醒門檻。",
        "額度提醒：gemini-3.5-flash 需注意（已用 80.0%）；保持目前模型，直到額度用完再自動降級。",
    ]
    rendered = str(captions)
    assert "Top-ranked configured model" not in rendered
    assert "warning" not in rendered
    assert "Keep using this model until exhausted." not in rendered


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
        "目前推薦：gemini-2.5-flash｜順位 2｜路由層級 後援模型｜約 10 分鐘 後重置",
        "額度提醒：gemini-3.5-flash 需注意；冷卻約 30 分鐘；不需手動操作。",
    ]
    rendered = str(captions)
    assert "tier=fallback" not in rendered
    assert "warning" not in rendered
    assert "cooldown" not in rendered
    assert "No manual action needed." not in rendered


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


def test_llm_usage_alert_rows_localize_codes_and_operator_actions() -> None:
    rows = llm_usage_alert_rows(
        {
            "alerts": [
                {
                    "severity": "error",
                    "code": "llm_cost_budget_exceeded",
                    "message": "LLM estimated cost is above the configured window budget.",
                },
                {
                    "severity": "warning",
                    "code": "llm_fallback_used",
                    "message": "Some LLM calls required fallback routing.",
                },
                {
                    "severity": "info",
                    "code": "llm_quota_routing_skips",
                    "message": (
                        "Some calls skipped exhausted or cooling-down models before "
                        "selecting a fallback."
                    ),
                },
                "ignored",
            ]
        }
    )

    assert rows == [
        {
            "嚴重度": "需處理",
            "提醒": "成本預算已超出",
            "下一步": "先暫停非必要分析，確認是否調高 LLM 成本預算。",
        },
        {
            "嚴重度": "需注意",
            "提醒": "曾使用後援模型",
            "下一步": "檢查主力模型是否額度用完、冷卻中或暫時失敗。",
        },
        {
            "嚴重度": "資訊",
            "提醒": "路由曾略過不可用模型",
            "下一步": "通常代表額度或冷卻保護生效；確認目前推薦模型即可。",
        },
    ]
    rendered = str(rows)
    assert "llm_cost_budget_exceeded" not in rendered
    assert "LLM estimated cost" not in rendered
    assert "fallback routing" not in rendered
    assert "cooling-down" not in rendered


def test_llm_usage_summary_rows_localize_daily_model_and_operation_tables() -> None:
    summary = {
        "daily": [
            {
                "date": "2026-06-09",
                "request_count": 7,
                "total_token_estimate": 1234,
                "estimated_cost_usd": 0.0123,
                "p95_latency_ms": 456.78,
                "fallback_path_count": 2,
                "retryable_failure_count": 4,
                "quota_skip_count": 3,
                "degraded_from_primary_count": 1,
            }
        ],
        "by_model": [
            {
                "model": "gemini-3.5-flash",
                "request_count": 5,
                "total_token_estimate": 1000,
                "estimated_cost_usd": 0.01,
                "p95_latency_ms": 300,
                "fallback_path_count": 1,
                "retryable_failure_count": 2,
                "quota_skip_count": 1,
                "degraded_from_primary_count": 1,
            }
        ],
        "by_operation": [
            {
                "operation": "report_generation",
                "request_count": 4,
                "total_token_estimate": 900,
                "estimated_cost_usd": 0.009,
                "p95_latency_ms": 250,
                "fallback_path_count": 1,
                "retryable_failure_count": 0,
                "quota_skip_count": 1,
                "degraded_from_primary_count": 1,
            }
        ],
    }

    assert llm_usage_daily_rows(summary) == [
        {
            "日期": "2026-06-09",
            "請求": 7,
            "Token": 1234,
            "估算成本 USD": "0.0123",
            "P95 延遲 ms": 456.78,
            "後援": 2,
            "可重試失敗": 4,
            "額度略過": 3,
            "模型降級": 1,
        }
    ]
    assert llm_usage_model_rows(summary) == [
        {
            "模型": "gemini-3.5-flash",
            "請求": 5,
            "Token": 1000,
            "估算成本 USD": "0.0100",
            "P95 延遲 ms": 300,
            "後援": 1,
            "可重試失敗": 2,
            "額度略過": 1,
            "模型降級": 1,
        }
    ]
    assert llm_usage_operation_rows(summary) == [
        {
            "任務": "報告生成",
            "請求": 4,
            "Token": 900,
            "估算成本 USD": "0.0090",
            "P95 延遲 ms": 250,
            "後援": 1,
            "可重試失敗": 0,
            "額度略過": 1,
            "模型降級": 1,
        }
    ]
    rendered = str(
        llm_usage_daily_rows(summary)
        + llm_usage_model_rows(summary)
        + llm_usage_operation_rows(summary)
    )
    assert "request_count" not in rendered
    assert "estimated_cost_usd" not in rendered
    assert "fallback_path_count" not in rendered
    assert "report_generation" not in rendered


def test_llm_usage_cost_budget_caption_localizes_status_and_budget_window() -> None:
    caption = llm_usage_cost_budget_caption(
        {
            "cost_budget": {
                "status": "exceeded",
                "window_cost_budget_usd": 0.01,
                "estimated_cost_usd": 0.025,
                "budget_used_ratio": 2.5,
            }
        }
    )

    assert caption == (
        "成本預算：已超出成本預算｜本期估算 $0.0250 / 預算 $0.0100｜已用 250.0%"
    )
    assert "exceeded" not in caption
    assert "window $" not in caption

    assert (
        llm_usage_cost_budget_caption(
            {
                "cost_budget": {
                    "status": "not_configured",
                    "estimated_cost_usd": 0.0,
                }
            }
        )
        == "成本預算：未設定成本預算｜本期估算 $0.0000｜設定每日成本預算後可提示超支"
    )
