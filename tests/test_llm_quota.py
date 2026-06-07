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
    primary = summary["models"][0]
    assert primary["model"] == "gemini-3.5-flash"
    assert primary["requests_used"] == 2
    assert primary["requests_remaining"] == 0
    assert primary["status"] == "exhausted"
    assert primary["status_reason"] == "request_budget_exhausted"
    assert primary["routing_tier"] == "primary"
    assert primary["routing_reason"].startswith("Skipped until the next quota window")
    assert summary["recommended_reason"] == (
        "Earlier model(s) exhausted in the current window: gemini-3.5-flash."
    )
    assert summary["routing_policy"]["strategy"] == "smartest_first_then_budget_degrade"
    assert summary["routing_policy"]["exhausted_before_recommendation"] == ["gemini-3.5-flash"]
    assert summary["routing_policy"]["high_quota_fallback_models"] == ["gemma-4-31b-it"]
    assert summary["totals"]["request_count"] == 2
    assert summary["window"]["timezone"] == "America/Los_Angeles"
