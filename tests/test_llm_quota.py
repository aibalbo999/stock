from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.services.llm_quota import LLMQuotaGovernanceService, parse_model_budget_map
from app.services.llm_quota_reference import (
    FREE_TIER_REQUEST_BUDGET_REFERENCES,
    parse_model_budget_map as reference_parse_model_budget_map,
    quota_reference_note,
    quota_reference_source,
)
from app.services.llm_quota_usage import quota_health_by_model, usage_by_model


def test_parse_model_budget_map_normalizes_provider_prefixes() -> None:
    expected = {
        "gemini-3.5-flash": 250,
        "gemma-4-31b-it": 14400,
    }
    assert (
        parse_model_budget_map(
            "models/gemini-3.5-flash=250,gemini/gemma-4-31b-it=14400,bad=x"
        )
        == reference_parse_model_budget_map(
            "models/gemini-3.5-flash=250,gemini/gemma-4-31b-it=14400,bad=x"
        )
        == expected
    )


def test_llm_quota_reference_catalog_lives_outside_governance_service() -> None:
    quota_source = Path("app/services/llm_quota.py").read_text()
    reference_source = Path("app/services/llm_quota_reference.py").read_text()

    assert "FREE_TIER_REQUEST_BUDGET_REFERENCES = {" not in quota_source
    assert "FREE_TIER_REQUEST_BUDGET_REFERENCES = {" in reference_source
    assert "def quota_reference_source(" not in quota_source
    assert "def quota_reference_source(" in reference_source
    assert FREE_TIER_REQUEST_BUDGET_REFERENCES["gemini-2.5-flash-lite"] == 1000
    assert quota_reference_source("gemini-2.5-flash-lite") == "google_free_tier_reference"
    assert (
        quota_reference_source("custom-model", unreferenced_source="unreferenced_project_config")
        == "unreferenced_project_config"
    )
    assert "Google Gemini API Free Tier" in quota_reference_note("gemini-2.5-flash-lite")


def test_llm_quota_usage_helpers_live_outside_governance_service() -> None:
    quota_source = Path("app/services/llm_quota.py").read_text()
    usage_source = Path("app/services/llm_quota_usage.py").read_text()
    records = [
        {
            "model": "gemini-2.5-flash",
            "models_tried": ["gemini-3.5-flash", "gemini-2.5-flash"],
            "attempts": [
                {
                    "model": "gemini-3.5-flash",
                    "outcome": "http_error",
                    "status": 429,
                    "retryable": True,
                },
                {
                    "model": "gemini-3.5-flash",
                    "outcome": "quota_cooldown",
                    "cooldown_seconds": 1800,
                    "retryable": True,
                },
                {"model": "gemini-2.5-flash", "outcome": "success"},
            ],
            "fallback": True,
            "total_token_estimate": 400,
            "estimated_cost_usd": 0.01,
            "created_at": "2026-06-07T11:40:00",
        }
    ]

    usage = usage_by_model(records)
    health = quota_health_by_model(
        records,
        now_utc_naive=datetime(2026, 6, 7, 12, 0, 0),
        default_cooldown_seconds=3600,
    )

    assert "def usage_by_model(" not in quota_source
    assert "def usage_by_model(" in usage_source
    assert "def quota_health_by_model(" not in quota_source
    assert "def quota_health_by_model(" in usage_source
    assert usage["gemini-3.5-flash"]["request_count"] == 1
    assert usage["gemini-3.5-flash"]["retryable_failure_count"] == 1
    assert usage["gemini-2.5-flash"]["completion_count"] == 1
    assert usage["gemini-2.5-flash"]["fallback_count"] == 1
    assert health["gemini-3.5-flash"]["quota_hit_count"] == 1
    assert health["gemini-3.5-flash"]["cooldown_skip_count"] == 1
    assert health["gemini-3.5-flash"]["active_cooldown_seconds"] == 2400


def test_llm_quota_service_recommends_next_available_model() -> None:
    settings = SimpleNamespace(
        primary_llm_model="gemini-3.5-flash",
        llm_fallback_models="gemini-2.5-flash,gemini-2.5-flash-lite,gemma-4-31b-it",
        local_llm_model="gemini-2.5-flash-lite",
        llm_quota_window_timezone="America/Los_Angeles",
        llm_quota_warning_ratio=0.8,
        llm_model_daily_request_budgets="gemini-3.5-flash=2,gemini-2.5-flash=250,gemma-4-31b-it=14400",
        llm_model_daily_token_budgets="gemini-3.5-flash=1000",
    )

    class FakeUsageRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def since(self, created_at: datetime):
            assert created_at.isoformat() == "2026-06-07T07:00:00"
            return [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        @staticmethod
        def to_dict(record):
            return {
                "id": record.id,
                "model": "models/gemini-3.5-flash",
                "fallback": False,
                "total_token_estimate": 400,
                "estimated_cost_usd": 0.0,
                "retryable_failure_count": 0,
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = LLMQuotaGovernanceService(
        settings_provider=lambda: settings,
        session_scope_factory=fake_session_scope,
        llm_usage_repository_cls=FakeUsageRepository,
        clock=lambda: datetime(2026, 6, 7, 12, 0, 0),
    )

    summary = service.summary()

    assert summary["recommended_model"] == "gemini-2.5-flash"
    assert summary["recommended_model_key"] == "gemini-2.5-flash"
    assert summary["recommended_rank"] == 2
    assert summary["recommended_routing_tier"] == "fallback"
    assert summary["recommended_status"] == "available"
    primary = summary["models"][0]
    fallback = summary["models"][1]
    assert primary["model"] == "gemini-3.5-flash"
    assert fallback["model"] == "gemini-2.5-flash"
    assert fallback["free_tier_request_budget_reference"] == 250
    assert fallback["free_tier_token_budget_reference"] == 250000
    assert fallback["quota_reference_source"] == "google_free_tier_reference"
    assert primary["requests_used"] == 2
    assert primary["requests_remaining"] == 0
    assert primary["request_used_ratio"] == 1.0
    assert primary["free_tier_request_budget_reference"] is None
    assert primary["quota_reference_source"] == "project_configured_ai_studio_limit"
    assert "user-confirmed smartest first model" in primary["quota_reference_note"]
    assert primary["status"] == "exhausted"
    assert primary["status_reason"] == "request_budget_exhausted"
    assert primary["risk_level"] == "exhausted"
    assert primary["quota_warning"] is False
    assert primary["routing_tier"] == "primary"
    assert primary["routing_reason"].startswith("已跳過此模型，直到下一個額度週期")
    assert primary["next_action"].startswith("路由會自動降級，不需手動操作")
    assert summary["recommended_reason"] == (
        "目前額度週期中，前序模型已用完：gemini-3.5-flash。"
    )
    assert summary["quota_warning_ratio"] == 0.8
    assert summary["alerts"][0]["code"] == "llm_quota_exhausted"
    assert summary["alerts"][0]["model"] == "gemini-3.5-flash"
    assert summary["routing_policy"]["strategy"] == "smartest_first_then_budget_degrade"
    assert summary["routing_policy"]["warning_rule"].startswith("用量達")
    assert summary["routing_policy"]["exhausted_before_recommendation"] == ["gemini-3.5-flash"]
    assert summary["routing_policy"]["high_quota_fallback_models"] == ["gemma-4-31b-it"]
    assert summary["totals"]["request_count"] == 2
    assert summary["totals"]["completion_count"] == 2
    assert summary["budget_source"]["free_tier_reference"]["scope"] == "project_level"
    assert summary["budget_source"]["free_tier_reference"]["request_budgets"][
        "gemini-2.5-flash"
    ] == 250
    assert summary["budget_source"]["free_tier_reference"]["request_budgets"][
        "gemini-2.5-flash-lite"
    ] == 1000
    assert "gemini-3.5-flash" in summary["budget_source"]["free_tier_reference"][
        "project_configured_model_notes"
    ]
    assert summary["window"]["timezone"] == "America/Los_Angeles"
    assert summary["window"]["now"] == "2026-06-07T05:00:00-07:00"
    assert summary["window"]["reset_in_seconds"] == 68399


def test_llm_quota_service_counts_attempted_models_for_hard_routing() -> None:
    settings = SimpleNamespace(
        primary_llm_model="gemini-3.5-flash",
        llm_fallback_models="gemini-2.5-flash,gemma-4-31b-it",
        local_llm_model="",
        llm_quota_window_timezone="America/Los_Angeles",
        llm_quota_warning_ratio=0.8,
        llm_model_daily_request_budgets="gemini-3.5-flash=1,gemini-2.5-flash=250,gemma-4-31b-it=14400",
        llm_model_daily_token_budgets="",
    )

    class FakeUsageRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def since(self, created_at: datetime):
            return [SimpleNamespace(id=1)]

        @staticmethod
        def to_dict(record):
            return {
                "id": record.id,
                "model": "gemini-2.5-flash",
                "models_tried": ["gemini-3.5-flash", "gemini-2.5-flash"],
                "attempts": [
                    {
                        "model": "gemini-3.5-flash",
                        "outcome": "http_error",
                        "status": 429,
                        "retryable": True,
                    },
                    {
                        "model": "gemini-2.5-flash",
                        "outcome": "success",
                    },
                ],
                "fallback": False,
                "total_token_estimate": 400,
                "estimated_cost_usd": 0.0,
                "retryable_failure_count": 1,
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = LLMQuotaGovernanceService(
        settings_provider=lambda: settings,
        session_scope_factory=fake_session_scope,
        llm_usage_repository_cls=FakeUsageRepository,
        clock=lambda: datetime(2026, 6, 7, 12, 0, 0),
    )

    summary = service.summary()
    primary, fallback = summary["models"][:2]

    assert summary["recommended_model"] == "gemini-2.5-flash"
    assert primary["model"] == "gemini-3.5-flash"
    assert primary["requests_used"] == 1
    assert primary["completion_count"] == 0
    assert primary["retryable_failure_count"] == 1
    assert primary["status"] == "exhausted"
    assert fallback["model"] == "gemini-2.5-flash"
    assert fallback["requests_used"] == 1
    assert fallback["completion_count"] == 1
    assert fallback["status"] == "available"
    assert summary["totals"]["request_count"] == 2
    assert summary["totals"]["completion_count"] == 1


def test_llm_quota_service_surfaces_quota_hits_and_active_cooldown() -> None:
    settings = SimpleNamespace(
        primary_llm_model="gemini-3.5-flash",
        llm_fallback_models="gemini-2.5-flash,gemma-4-31b-it",
        local_llm_model="",
        llm_quota_window_timezone="America/Los_Angeles",
        llm_quota_warning_ratio=0.8,
        llm_model_daily_request_budgets="gemini-3.5-flash=250,gemini-2.5-flash=250,gemma-4-31b-it=14400",
        llm_model_daily_token_budgets="",
        llm_model_quota_cooldown_seconds=3600,
    )

    class FakeUsageRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def since(self, created_at: datetime):
            return [SimpleNamespace(id=1)]

        @staticmethod
        def to_dict(record):
            return {
                "id": record.id,
                "model": "gemini-2.5-flash",
                "models_tried": ["gemini-3.5-flash", "gemini-2.5-flash"],
                "attempts": [
                    {
                        "model": "gemini-3.5-flash",
                        "outcome": "http_error",
                        "status": 429,
                        "retryable": True,
                    },
                    {
                        "model": "gemini-3.5-flash",
                        "outcome": "quota_cooldown",
                        "retryable": True,
                        "cooldown_seconds": 1800,
                    },
                    {
                        "model": "gemini-2.5-flash",
                        "outcome": "success",
                    },
                ],
                "fallback": True,
                "total_token_estimate": 400,
                "estimated_cost_usd": 0.0,
                "retryable_failure_count": 1,
                "created_at": "2026-06-07T11:40:00",
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = LLMQuotaGovernanceService(
        settings_provider=lambda: settings,
        session_scope_factory=fake_session_scope,
        llm_usage_repository_cls=FakeUsageRepository,
        clock=lambda: datetime(2026, 6, 7, 12, 0, 0),
    )

    summary = service.summary()
    primary, fallback = summary["models"][:2]

    assert summary["recommended_model"] == "gemini-2.5-flash"
    assert primary["status"] == "cooldown"
    assert primary["risk_level"] == "cooldown"
    assert primary["status_reason"] == "quota_cooldown_active"
    assert primary["quota_hit_count"] == 1
    assert primary["quota_skip_count"] == 1
    assert primary["cooldown_skip_count"] == 1
    assert primary["active_cooldown_seconds"] == 2400
    assert primary["last_quota_hit_at"] == "2026-06-07T11:40:00"
    assert primary["routing_reason"].startswith("暫時略過此模型")
    assert fallback["status"] == "available"
    assert summary["routing_policy"]["quota_hit_models"] == ["gemini-3.5-flash"]
    assert summary["routing_policy"]["cooldown_models"] == ["gemini-3.5-flash"]
    assert summary["alerts"][0]["code"] == "llm_quota_cooldown"
    assert summary["alerts"][0]["active_cooldown_seconds"] == 2400
    assert service.exhausted_model_keys() == {"gemini-3.5-flash"}
    assert service.active_cooldown_seconds("gemini/gemini-3.5-flash") == 2400.0


def test_llm_quota_service_warns_near_limit_without_degrading_model() -> None:
    settings = SimpleNamespace(
        primary_llm_model="gemini-3.5-flash",
        llm_fallback_models="gemini-2.5-flash,gemma-4-31b-it",
        local_llm_model="",
        llm_quota_window_timezone="America/Los_Angeles",
        llm_quota_warning_ratio=0.8,
        llm_model_daily_request_budgets="gemini-3.5-flash=10,gemini-2.5-flash=250,gemma-4-31b-it=14400",
        llm_model_daily_token_budgets="",
    )

    class FakeUsageRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def since(self, created_at: datetime):
            return [SimpleNamespace(id=index) for index in range(8)]

        @staticmethod
        def to_dict(record):
            return {
                "id": record.id,
                "model": "gemini-3.5-flash",
                "fallback": False,
                "total_token_estimate": 100,
                "estimated_cost_usd": 0.0,
                "retryable_failure_count": 0,
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = LLMQuotaGovernanceService(
        settings_provider=lambda: settings,
        session_scope_factory=fake_session_scope,
        llm_usage_repository_cls=FakeUsageRepository,
        clock=lambda: datetime(2026, 6, 7, 12, 0, 0),
    )

    summary = service.summary()
    primary = summary["models"][0]

    assert summary["recommended_model"] == "gemini-3.5-flash"
    assert summary["recommended_rank"] == 1
    assert summary["recommended_reason"] == (
        "最高順位已設定模型仍有可追蹤額度；目前已達 80% 提醒門檻。"
    )
    assert primary["status"] == "available"
    assert primary["status_reason"] == "request_budget_near_limit"
    assert primary["risk_level"] == "warning"
    assert primary["quota_warning"] is True
    assert primary["requests_used"] == 8
    assert primary["requests_remaining"] == 2
    assert primary["request_used_ratio"] == 0.8
    assert primary["routing_reason"].startswith("額度用完前仍可使用")
    assert summary["routing_policy"]["exhausted_before_recommendation"] == []
    assert summary["alerts"] == [
        {
            "code": "llm_quota_near_limit",
            "severity": "warning",
            "model": "gemini-3.5-flash",
            "model_key": "gemini-3.5-flash",
            "risk_level": "warning",
            "status": "available",
            "status_reason": "request_budget_near_limit",
            "usage_ratio": 0.8,
            "requests_used": 8,
            "request_budget": 10,
            "requests_remaining": 2,
            "tokens_used": 800,
            "token_budget": None,
            "tokens_remaining": None,
            "quota_hit_count": 0,
            "quota_skip_count": 0,
            "active_cooldown_seconds": 0,
            "last_quota_hit_at": None,
            "next_action": "額度用完前可繼續使用；若需保留剩餘額度，請延後大型批次任務。",
            "message": "gemini-3.5-flash is near its configured daily request budget.",
        }
    ]
