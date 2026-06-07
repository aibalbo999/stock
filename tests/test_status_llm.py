from pathlib import Path

from app.core.config import Settings
from app.services.llm_client import DEFAULT_MAX_RETRIES_PER_KEY, RETRYABLE_HTTP_STATUSES
from app.services.service_status import service_status
from app.services.status_llm import (
    _llm_fallback_readiness,
    _llm_model_provider,
    _llm_quota_routing_status,
)


def test_llm_status_retry_quota_and_observability_shape() -> None:
    status = service_status()
    service_status_source = Path("app/services/service_status.py").read_text()
    status_llm_source = Path("app/services/status_llm.py").read_text()

    assert status["gemini"]["retryable_http_statuses"] == sorted(RETRYABLE_HTTP_STATUSES)
    assert status["gemini"]["max_retries_per_key"] == DEFAULT_MAX_RETRIES_PER_KEY
    assert status["gemini"]["base_retry_delay_seconds"] == 0.5
    assert status["gemini"]["max_retry_delay_seconds"] == 5.0
    assert status["gemini"]["provider_keys_configured"]["anthropic"] is False
    assert status["llm_quota_routing"]["ready"] is True
    assert status["llm_quota_routing"]["collector_path"] == "app/services/status_llm.py"
    assert "from app.services.status_llm import (" in service_status_source
    assert "def _llm_quota_routing_status(" not in service_status_source
    assert "def _llm_quota_routing_status(" in status_llm_source
    assert status["llm_quota_routing"]["strategy"] == "smartest_first_then_budget_degrade"
    assert status["llm_quota_routing"]["model_order"][:4] == [
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
    ]
    assert status["llm_quota_routing"]["same_tier_flash_request_budgets"] == {
        "gemini-3.5-flash": 250,
        "gemini-2.5-flash": 250,
        "gemini-3.1-flash-lite": 250,
        "gemini-2.5-flash-lite": 250,
    }
    assert status["llm_quota_routing"]["high_quota_fallback_request_budget"] == 14400
    assert status["llm_quota_routing"]["readiness_checks"]["hard_routing_enabled"] is True
    assert status["llm_quota_routing"]["excluded_media_live_models"] == []
    assert status["llm_observability"]["enabled"] is True
    assert status["llm_observability"]["local_trace_enabled"] is True
    assert "latency_ms" in status["llm_observability"]["captured_fields"]
    assert "total_token_estimate" in status["llm_observability"]["captured_fields"]


def test_ai_rag_llm_capability_matrix_evidence() -> None:
    status = service_status()
    matrix = status["upgrade_capability_matrix"]

    llm_matrix = matrix["ai_rag"]["llm_sdk_and_fallback"]
    llm_evidence = llm_matrix["evidence"]
    assert "sdk_ready" in llm_evidence
    assert "fallback_model_ready_count" in llm_evidence
    if llm_evidence["fallback_model_count"] == 0:
        assert llm_matrix["status"] == "degraded"
    else:
        expected_llm_status = (
            "ready"
            if llm_evidence["sdk_ready"] and llm_evidence["fallback_model_ready_count"] > 0
            else "degraded"
        )
        assert llm_matrix["status"] == expected_llm_status

    assert matrix["ai_rag"]["llm_observability"]["status"] == "ready"
    assert matrix["ai_rag"]["llm_observability"]["evidence"]["local_trace_enabled"] is True
    assert "latency_ms" in matrix["ai_rag"]["llm_observability"]["evidence"]["captured_fields"]
    assert (
        "total_token_estimate"
        in matrix["ai_rag"]["llm_observability"]["evidence"]["captured_fields"]
    )
    quota_routing = matrix["ai_rag"]["llm_quota_routing"]
    assert quota_routing["status"] == "ready"
    assert quota_routing["evidence"]["readiness_checks"]["flash_models_share_request_budget"] is True
    assert (
        quota_routing["evidence"]["readiness_checks"]["high_quota_fallback_after_smart_models"]
        is True
    )
    assert quota_routing["evidence"]["readiness_checks"]["embedding_model_kept_separate"] is True


def test_llm_retry_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_max_retries_per_key == DEFAULT_MAX_RETRIES_PER_KEY
    assert settings.llm_base_retry_delay_seconds == 0.5
    assert settings.llm_max_retry_delay_seconds == 5.0
    assert settings.primary_llm_model == "gemini-3.5-flash"
    assert settings.local_llm_model == "gemini-2.5-flash-lite"
    assert (
        settings.llm_fallback_models
        == "gemini-2.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemma-4-31b-it"
    )
    assert settings.llm_model_quota_cooldown_seconds == 3600
    assert settings.llm_quota_window_timezone == "America/Los_Angeles"
    assert "gemini-3.5-flash=250" in settings.llm_model_daily_request_budgets
    assert settings.llm_model_cost_rate_card_usd == ""
    assert settings.llm_daily_cost_budget_usd == 0.0
    assert settings.llm_cost_warning_ratio == 0.8
    assert settings.task_observability_stale_minutes == 60


def test_llm_quota_routing_status_requires_smart_first_order_and_equal_budgets() -> None:
    ready = _llm_quota_routing_status(Settings(_env_file=None))

    assert ready["ready"] is True
    assert ready["collector_path"] == "app/services/status_llm.py"
    assert ready["failed_checks"] == []
    assert ready["readiness_checks"]["smart_model_order"] is True
    assert ready["readiness_checks"]["flash_models_share_request_budget"] is True
    assert ready["readiness_checks"]["high_quota_fallback_budget_ready"] is True

    misordered = _llm_quota_routing_status(
        Settings(
            _env_file=None,
            llm_fallback_models=(
                "gemma-4-31b-it,gemini-2.5-flash,"
                "gemini-3.1-flash-lite,gemini-2.5-flash-lite"
            ),
        )
    )
    assert misordered["ready"] is False
    assert "smart_model_order" in misordered["failed_checks"]
    assert "high_quota_fallback_after_smart_models" in misordered["failed_checks"]

    unequal_budget = _llm_quota_routing_status(
        Settings(
            _env_file=None,
            llm_model_daily_request_budgets=(
                "gemini-3.5-flash=250,gemini-2.5-flash=250,"
                "gemini-3.1-flash-lite=100,gemini-2.5-flash-lite=250,"
                "gemma-4-31b-it=14400"
            ),
        )
    )
    assert unequal_budget["ready"] is False
    assert "flash_models_share_request_budget" in unequal_budget["failed_checks"]


def test_llm_model_provider_classifies_fallback_models() -> None:
    assert _llm_model_provider("gemini-2.5-flash") == "gemini"
    assert _llm_model_provider("gemini/gemini-2.5-flash") == "gemini"
    assert _llm_model_provider("claude-3-5-haiku") == "anthropic"
    assert _llm_model_provider("anthropic/claude-3-5-haiku") == "anthropic"
    assert _llm_model_provider("gpt-4o-mini") == "openai"
    assert _llm_model_provider("openai/gpt-4o-mini") == "openai"
    assert _llm_model_provider("gemma-4-31b-it") == "gemini"
    assert _llm_model_provider("ollama/gemma3:27b") == "local"
    assert _llm_model_provider("custom/provider") == "unknown"


def test_llm_fallback_readiness_requires_matching_provider_key() -> None:
    rows = _llm_fallback_readiness(
        [
            "claude-3-5-haiku",
            "gpt-4o-mini",
            "gemini/gemini-backup",
            "gemma-4-31b-it",
            "custom/provider",
        ],
        {"gemini": True, "openai": False, "anthropic": True, "local": True},
    )

    assert rows == [
        {"model": "claude-3-5-haiku", "provider": "anthropic", "key_configured": True},
        {"model": "gpt-4o-mini", "provider": "openai", "key_configured": False},
        {"model": "gemini/gemini-backup", "provider": "gemini", "key_configured": True},
        {"model": "gemma-4-31b-it", "provider": "gemini", "key_configured": True},
        {"model": "custom/provider", "provider": "unknown", "key_configured": None},
    ]
