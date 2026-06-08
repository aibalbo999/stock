from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from app.services.llm_api import LLMApiService
from app.services.llm_client import LLMResult


def test_llm_api_service_reports_status_from_settings() -> None:
    settings = SimpleNamespace(
        primary_llm_model="gemini-2.5-flash",
        local_llm_model="gemma-4-31b-it",
        gemini_api_keys=["a", "b"],
        llm_provider="litellm",
        llm_fallback_models="claude-3-5-haiku,gpt-4o-mini",
        openai_api_key="openai-key",
        anthropic_api_key="anthropic-key",
        llm_max_retries_per_key=2,
        llm_model_quota_cooldown_seconds=3600,
        llm_base_retry_delay_seconds=0.5,
        llm_max_retry_delay_seconds=5.0,
        llm_observability_enabled=True,
        llm_observability_provider="local",
        llm_observability_external_dispatch_enabled=True,
        llm_observability_project_name="stock-analysis",
        llm_observability_export_timeout_seconds=2.0,
        llm_input_cost_per_1k_tokens_usd=0.0,
        llm_output_cost_per_1k_tokens_usd=0.0,
        llm_model_cost_rate_card_usd="",
        llm_daily_cost_budget_usd=0.0,
        llm_cost_warning_ratio=0.8,
        langsmith_api_key=None,
        langsmith_endpoint="",
        phoenix_endpoint="",
        phoenix_api_key=None,
    )

    status = LLMApiService(settings_provider=lambda: settings).status()

    assert status == {
        "primary_model": "gemini-2.5-flash",
        "local_model": "gemma-4-31b-it",
        "gemini_key_count": 2,
        "enabled": True,
        "provider": "litellm",
        "sdk_dependency": "litellm",
        "sdk_dependency_available": LLMApiService._module_available("litellm"),
        "fallback_models": ["claude-3-5-haiku", "gpt-4o-mini", "gemma-4-31b-it"],
        "fallback_model_readiness": [
            {"model": "claude-3-5-haiku", "provider": "anthropic", "key_configured": True},
            {"model": "gpt-4o-mini", "provider": "openai", "key_configured": True},
            {"model": "gemma-4-31b-it", "provider": "gemini", "key_configured": True},
        ],
        "fallback_model_ready_count": 3,
        "provider_keys_configured": {
            "gemini": True,
            "openai": True,
            "anthropic": True,
            "local": False,
        },
        "observability": {
            "enabled": True,
            "provider": "local",
            "supported_providers": ["local", "langsmith", "phoenix"],
            "local_trace_enabled": True,
            "external_trace_configured": False,
            "external_trace_ready": False,
            "external_trace_missing_settings": [],
            "external_trace_missing_dependencies": [],
            "trace_export_mode": "local_trace",
            "trace_export_target": "local",
            "external_dispatch_enabled": True,
            "best_effort_external_dispatch": True,
            "external_trace_export_supported": True,
            "external_trace_export_providers": ["langsmith", "phoenix"],
            "external_trace_export_function": (
                "app.services.llm_observability.export_llm_observability_trace"
            ),
            "export_timeout_seconds": 2.0,
            "trace_sink": {
                "provider": "local",
                "label": "Local usage store",
                "supported": True,
                "enabled": True,
                "external_sink": False,
                "configured": True,
                "ready": True,
                "dispatch_enabled": True,
                "external_trace_configured": False,
                "missing_settings": [],
                "missing_dependencies": [],
                "required_settings": [],
                "optional_settings": [],
                "dependency_modules": [],
                "dependency_available": True,
                "install_extra": None,
                "api_key_setting": None,
                "api_key_configured": None,
                "endpoint_setting": None,
                "endpoint_configured": None,
                "trace_export_mode": "local_trace",
                "trace_export_target": "local",
            },
            "langsmith_configured": False,
            "phoenix_endpoint_configured": False,
            "phoenix_api_key_configured": False,
            "captured_fields": [
                "provider",
                "model",
                "routing_decision",
                "selected_model_rank",
                "selected_routing_tier",
                "quota_skip_count",
                "daily_quota_skip_count",
                "cooldown_skip_count",
                "latency_ms",
                "attempt_count",
                "models_tried",
                "fallback_path_used",
                "primary_failure_category",
                "external_trace_provider",
                "trace_export_mode",
                "external_trace_dispatch",
                "input_token_estimate",
                "output_token_estimate",
                "total_token_estimate",
                "estimated_cost_usd",
                "cost_tracking_mode",
                "retrieval_latency_ms",
                "reranker_status",
            ],
            "cost_tracking_enabled": True,
            "cost_rate_card_configured": False,
            "model_cost_rate_card_count": 0,
            "daily_cost_budget_usd": 0.0,
            "cost_warning_ratio": 0.8,
            "input_cost_per_1k_tokens_usd_configured": False,
            "output_cost_per_1k_tokens_usd_configured": False,
        },
        "quota_routing": {
            "available": False,
            "reason": "usage_store_unavailable",
            "recommended_model": None,
            "exhausted_models": [],
            "high_quota_fallback_models": [],
            "models": [],
            "totals": {},
        },
        "retry_policy": {
            "max_retries_per_key": 2,
            "model_quota_cooldown_seconds": 3600.0,
            "base_retry_delay_seconds": 0.5,
            "max_retry_delay_seconds": 5.0,
        },
    }


def test_llm_api_service_healthcheck_truncates_message_and_sets_ok() -> None:
    class FakeClient:
        def healthcheck(self):
            return LLMResult(
                text="x" * 250,
                key_index=1,
                model="gemini/gemini-2.5-flash",
                provider="litellm",
                fallback=False,
                attempts=(
                    {
                        "provider": "litellm",
                        "model": "gemini/gemini-2.5-flash",
                        "outcome": "success",
                        "key_index": 1,
                        "attempt": 1,
                    },
                ),
            )

    payload = LLMApiService(llm_client_cls=FakeClient).healthcheck()

    assert payload == {
        "ok": True,
        "model": "gemini/gemini-2.5-flash",
        "key_index": 1,
        "provider": "litellm",
        "fallback": False,
        "message": "x" * 200,
        "attempts": [
            {
                "provider": "litellm",
                "model": "gemini/gemini-2.5-flash",
                "outcome": "success",
                "key_index": 1,
                "attempt": 1,
            }
        ],
        "attempt_summary": {
            "attempt_count": 1,
            "providers_tried": ["litellm"],
            "models_tried": ["gemini/gemini-2.5-flash"],
            "outcome_counts": {"success": 1},
            "failure_category_counts": {},
            "http_status_counts": {},
            "failed_attempt_count": 0,
            "successful_attempt_count": 1,
            "retryable_failure_count": 0,
            "retry_used": False,
            "success_after_failure": False,
            "provider_fallback_used": False,
            "model_fallback_used": False,
            "fallback_path_used": False,
            "primary_failure_category": None,
            "last_failure_category": None,
            "primary_provider": "litellm",
            "primary_model": "gemini/gemini-2.5-flash",
            "final_provider": "litellm",
            "final_model": "gemini/gemini-2.5-flash",
            "final_outcome": "success",
            "final_success": True,
        },
        "observability": {},
    }


def test_llm_api_service_lists_usage_records_from_repository() -> None:
    class FakeUsageRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def latest(self, limit: int):
            assert self.session == "session"
            assert limit == 3
            return [SimpleNamespace(id=1)]

        @staticmethod
        def to_dict(record):
            return {"id": record.id, "model": "gemini-3.5-flash"}

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = LLMApiService(
        session_scope_factory=fake_session_scope,
        llm_usage_repository_cls=FakeUsageRepository,
    )

    assert service.usage_records(3) == [{"id": 1, "model": "gemini-3.5-flash"}]


def test_llm_api_service_returns_quota_summary() -> None:
    captured = {}

    class FakeQuotaService:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def summary(self) -> dict:
            return {"recommended_model": "gemini-3.5-flash"}

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = LLMApiService(
        session_scope_factory=fake_session_scope,
        llm_quota_service_cls=FakeQuotaService,
    )

    assert service.quota_summary() == {"recommended_model": "gemini-3.5-flash"}
    assert captured["session_scope_factory"] is fake_session_scope


def test_llm_api_status_embeds_compact_quota_routing_snapshot() -> None:
    settings = SimpleNamespace(
        primary_llm_model="gemini-3.5-flash",
        local_llm_model="gemini-2.5-flash-lite",
        gemini_api_keys=["key"],
        llm_provider="google_genai",
        llm_fallback_models="gemini-2.5-flash,gemma-4-31b-it",
        openai_api_key=None,
        anthropic_api_key=None,
        llm_max_retries_per_key=1,
        llm_model_quota_cooldown_seconds=3600,
        llm_base_retry_delay_seconds=0.5,
        llm_max_retry_delay_seconds=5.0,
        llm_observability_enabled=True,
        llm_observability_provider="local",
        llm_input_cost_per_1k_tokens_usd=0.0,
        llm_output_cost_per_1k_tokens_usd=0.0,
        llm_model_cost_rate_card_usd="",
        llm_daily_cost_budget_usd=0.0,
        llm_cost_warning_ratio=0.8,
        langsmith_api_key=None,
        phoenix_endpoint="",
    )
    captured = {}

    class FakeQuotaService:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def summary(self) -> dict:
            return {
                "recommended_model": "gemini-2.5-flash",
                "recommended_model_key": "gemini-2.5-flash",
                "recommended_rank": 2,
                "recommended_routing_tier": "fallback",
                "recommended_status": "available",
                "recommended_reason": "Earlier model(s) exhausted in the current window: gemini-3.5-flash.",
                "model_order": ["gemini-3.5-flash", "gemini-2.5-flash", "gemma-4-31b-it"],
                "window": {
                    "timezone": "America/Los_Angeles",
                    "reset_in_seconds": 5400,
                },
                "totals": {
                    "request_count": 3,
                    "completion_count": 2,
                    "total_token_estimate": 1200,
                    "estimated_cost_usd": 0.0,
                    "ignored_extra": "not exposed",
                },
                "routing_policy": {
                    "strategy": "smartest_first_then_budget_degrade",
                    "selection_rule": "Use the first configured model that is not exhausted.",
                    "high_quota_fallback_models": ["gemma-4-31b-it"],
                },
                "models": [
                    {
                        "rank": 1,
                        "model": "gemini-3.5-flash",
                        "status": "exhausted",
                        "status_reason": "request_budget_exhausted",
                        "routing_tier": "primary",
                        "routing_reason": "Skipped until the next quota window.",
                        "requests_used": 1,
                        "request_budget": 1,
                        "requests_remaining": 0,
                        "completion_count": 0,
                        "tokens_used": 0,
                        "token_budget": None,
                        "tokens_remaining": None,
                        "estimated_cost_usd": 99.0,
                    },
                    {
                        "rank": 2,
                        "model": "gemini-2.5-flash",
                        "status": "available",
                        "status_reason": "within_configured_budget",
                        "routing_tier": "fallback",
                        "routing_reason": "Fallback candidate.",
                        "requests_used": 2,
                        "request_budget": 250,
                        "requests_remaining": 248,
                        "completion_count": 2,
                        "tokens_used": 1200,
                        "token_budget": None,
                        "tokens_remaining": None,
                    },
                ],
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    status = LLMApiService(
        settings_provider=lambda: settings,
        session_scope_factory=fake_session_scope,
        llm_quota_service_cls=FakeQuotaService,
    ).status()

    assert captured["session_scope_factory"] is fake_session_scope
    quota = status["quota_routing"]
    assert quota["available"] is True
    assert quota["strategy"] == "smartest_first_then_budget_degrade"
    assert quota["recommended_model"] == "gemini-2.5-flash"
    assert quota["recommended_model_key"] == "gemini-2.5-flash"
    assert quota["recommended_rank"] == 2
    assert quota["recommended_routing_tier"] == "fallback"
    assert quota["recommended_status"] == "available"
    assert quota["exhausted_models"] == ["gemini-3.5-flash"]
    assert quota["high_quota_fallback_models"] == ["gemma-4-31b-it"]
    assert quota["window"]["reset_in_seconds"] == 5400
    assert quota["totals"] == {
        "request_count": 3,
        "completion_count": 2,
        "total_token_estimate": 1200,
        "estimated_cost_usd": 0.0,
    }
    assert quota["models"][0] == {
        "rank": 1,
        "model": "gemini-3.5-flash",
        "status": "exhausted",
        "status_reason": "request_budget_exhausted",
        "routing_tier": "primary",
        "routing_reason": "Skipped until the next quota window.",
        "requests_used": 1,
        "request_budget": 1,
        "requests_remaining": 0,
        "completion_count": 0,
        "tokens_used": 0,
        "token_budget": None,
        "tokens_remaining": None,
    }
    assert "estimated_cost_usd" not in quota["models"][0]


def test_llm_api_service_returns_usage_summary() -> None:
    class FakeUsageRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def since(self, created_at):
            assert self.session == "session"
            assert created_at is not None
            return [SimpleNamespace(id=1)]

        @staticmethod
        def to_dict(record):
            return {
                "id": record.id,
                "operation": "report_generation",
                "model": "gemini-3.5-flash",
                "provider": "google_genai",
                "fallback": False,
                "fallback_path_used": True,
                "latency_ms": 120.0,
                "total_token_estimate": 99,
                "estimated_cost_usd": 0.0123,
                "attempt_count": 2,
                "retryable_failure_count": 1,
                "observability": {
                    "routing_decision": {
                        "selected_model_rank": 2,
                        "selected_routing_tier": "fallback",
                        "routing_reason": "quota_or_cooldown_skip",
                        "quota_skip_count": 1,
                        "daily_quota_skip_count": 1,
                        "cooldown_skip_count": 0,
                        "degraded_from_primary": True,
                        "high_quota_fallback_used": False,
                    },
                    "quota_skip_count": 1,
                    "daily_quota_skip_count": 1,
                    "cooldown_skip_count": 0,
                    "degraded_from_primary": True,
                },
                "created_at": "2026-06-07T08:00:00",
            }

    class FakeQuotaService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def summary(self) -> dict:
            return {
                "recommended_model": "gemini-3.5-flash",
                "recommended_model_key": "gemini-3.5-flash",
                "recommended_rank": 1,
                "recommended_routing_tier": "primary",
                "recommended_status": "available",
                "recommended_reason": "Primary model remains within the current quota window.",
                "model_order": ["gemini-3.5-flash", "gemini-2.5-flash", "gemma-4-31b-it"],
                "routing_policy": {
                    "strategy": "smartest_first_then_budget_degrade",
                    "selection_rule": "Use the first configured model that is not exhausted.",
                    "high_quota_fallback_models": ["gemma-4-31b-it"],
                },
                "window": {"reset_in_seconds": 5400},
                "totals": {
                    "request_count": 1,
                    "completion_count": 1,
                    "total_token_estimate": 99,
                    "estimated_cost_usd": 0.0123,
                },
                "models": [
                    {
                        "rank": 1,
                        "model": "gemini-3.5-flash",
                        "status": "available",
                        "status_reason": "within_configured_budget",
                        "routing_tier": "primary",
                        "routing_reason": "Primary candidate.",
                        "requests_used": 1,
                        "request_budget": 250,
                        "requests_remaining": 249,
                        "completion_count": 1,
                        "tokens_used": 99,
                        "token_budget": None,
                        "tokens_remaining": None,
                    }
                ],
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    service = LLMApiService(
        session_scope_factory=fake_session_scope,
        llm_usage_repository_cls=FakeUsageRepository,
        llm_quota_service_cls=FakeQuotaService,
    )

    summary = service.usage_summary(7)

    assert summary["totals"]["request_count"] == 1
    assert summary["totals"]["total_token_estimate"] == 99
    assert summary["totals"]["fallback_path_count"] == 1
    assert summary["totals"]["quota_skip_count"] == 1
    assert summary["totals"]["daily_quota_skip_count"] == 1
    assert summary["totals"]["cooldown_skip_count"] == 0
    assert summary["totals"]["degraded_from_primary_count"] == 1
    assert summary["recent"][0]["selected_model_rank"] == 2
    assert summary["recent"][0]["selected_routing_tier"] == "fallback"
    assert summary["recent"][0]["routing_reason"] == "quota_or_cooldown_skip"
    assert summary["by_model"][0]["model"] == "gemini-3.5-flash"
    assert summary["by_model"][0]["quota_skip_count"] == 1
    assert summary["by_operation"][0]["operation"] == "report_generation"
    assert summary["routing_snapshot"]["available"] is True
    assert summary["routing_snapshot"]["strategy"] == "smartest_first_then_budget_degrade"
    assert summary["routing_snapshot"]["recommended_model"] == "gemini-3.5-flash"
    assert summary["routing_snapshot"]["high_quota_fallback_models"] == ["gemma-4-31b-it"]
    assert summary["routing_snapshot"]["models"][0] == {
        "rank": 1,
        "model": "gemini-3.5-flash",
        "status": "available",
        "status_reason": "within_configured_budget",
        "routing_tier": "primary",
        "routing_reason": "Primary candidate.",
        "requests_used": 1,
        "request_budget": 250,
        "requests_remaining": 249,
        "completion_count": 1,
        "tokens_used": 99,
        "token_budget": None,
        "tokens_remaining": None,
    }


def test_llm_api_usage_summary_flags_cost_budget_and_fallback_alerts() -> None:
    class FakeUsageRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def since(self, created_at):
            return [SimpleNamespace(id=1)]

        @staticmethod
        def to_dict(record):
            return {
                "id": record.id,
                "operation": "visual_rag",
                "model": "gemini-3.5-flash",
                "provider": "google_genai",
                "fallback": False,
                "fallback_path_used": True,
                "latency_ms": 900.0,
                "total_token_estimate": 1200,
                "estimated_cost_usd": 0.0123,
                "attempt_count": 2,
                "retryable_failure_count": 1,
                "created_at": "2026-06-07T08:00:00",
            }

    @contextmanager
    def fake_session_scope():
        yield "session"

    settings = SimpleNamespace(
        llm_observability_enabled=True,
        llm_observability_provider="local",
        llm_input_cost_per_1k_tokens_usd=0.0,
        llm_output_cost_per_1k_tokens_usd=0.0,
        llm_model_cost_rate_card_usd="gemini-3.5-flash=0.000075:0.0003",
        llm_daily_cost_budget_usd=0.01,
        llm_cost_warning_ratio=0.8,
        langsmith_api_key=None,
        phoenix_endpoint="",
    )
    service = LLMApiService(
        settings_provider=lambda: settings,
        session_scope_factory=fake_session_scope,
        llm_usage_repository_cls=FakeUsageRepository,
    )

    summary = service.usage_summary(1)

    assert summary["cost_budget"]["status"] == "exceeded"
    assert summary["cost_budget"]["window_cost_budget_usd"] == 0.01
    assert {alert["code"] for alert in summary["alerts"]} == {
        "llm_cost_budget_exceeded",
        "llm_fallback_used",
        "llm_retryable_failures",
    }
