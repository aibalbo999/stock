from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from app.services.llm_quota import LLMQuotaGovernanceService, parse_model_budget_map


def test_parse_model_budget_map_normalizes_provider_prefixes() -> None:
    assert parse_model_budget_map("models/gemini-3.5-flash=250,gemini/gemma-4-31b-it=14400,bad=x") == {
        "gemini-3.5-flash": 250,
        "gemma-4-31b-it": 14400,
    }


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
    assert primary["model"] == "gemini-3.5-flash"
    assert primary["requests_used"] == 2
    assert primary["requests_remaining"] == 0
    assert primary["request_used_ratio"] == 1.0
    assert primary["status"] == "exhausted"
    assert primary["status_reason"] == "request_budget_exhausted"
    assert primary["risk_level"] == "exhausted"
    assert primary["quota_warning"] is False
    assert primary["routing_tier"] == "primary"
    assert primary["routing_reason"].startswith("Skipped until the next quota window")
    assert primary["next_action"].startswith("No action needed for routing")
    assert summary["recommended_reason"] == (
        "Earlier model(s) exhausted in the current window: gemini-3.5-flash."
    )
    assert summary["quota_warning_ratio"] == 0.8
    assert summary["alerts"][0]["code"] == "llm_quota_exhausted"
    assert summary["alerts"][0]["model"] == "gemini-3.5-flash"
    assert summary["routing_policy"]["strategy"] == "smartest_first_then_budget_degrade"
    assert summary["routing_policy"]["warning_rule"].startswith("Warning thresholds")
    assert summary["routing_policy"]["exhausted_before_recommendation"] == ["gemini-3.5-flash"]
    assert summary["routing_policy"]["high_quota_fallback_models"] == ["gemma-4-31b-it"]
    assert summary["totals"]["request_count"] == 2
    assert summary["totals"]["completion_count"] == 2
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
        "Top-ranked configured model still has remaining tracked quota; "
        "it has reached the 80% warning threshold."
    )
    assert primary["status"] == "available"
    assert primary["status_reason"] == "request_budget_near_limit"
    assert primary["risk_level"] == "warning"
    assert primary["quota_warning"] is True
    assert primary["requests_used"] == 8
    assert primary["requests_remaining"] == 2
    assert primary["request_used_ratio"] == 0.8
    assert primary["routing_reason"].startswith("Still eligible until exhausted")
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
            "next_action": (
                "Keep using this model until exhausted; defer large batch runs if you need "
                "to preserve its remaining quota."
            ),
            "message": "gemini-3.5-flash is near its configured daily request budget.",
        }
    ]
