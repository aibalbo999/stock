from __future__ import annotations

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
        llm_base_retry_delay_seconds=0.5,
        llm_max_retry_delay_seconds=5.0,
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
        "retry_policy": {
            "max_retries_per_key": 2,
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
    }
