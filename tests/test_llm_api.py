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
        llm_input_cost_per_1k_tokens_usd=0.0,
        llm_output_cost_per_1k_tokens_usd=0.0,
        langsmith_api_key=None,
        phoenix_endpoint="",
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
            "langsmith_configured": False,
            "phoenix_endpoint_configured": False,
            "captured_fields": [
                "provider",
                "model",
                "latency_ms",
                "attempt_count",
                "models_tried",
                "fallback_path_used",
                "primary_failure_category",
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
            "input_cost_per_1k_tokens_usd_configured": False,
            "output_cost_per_1k_tokens_usd_configured": False,
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
