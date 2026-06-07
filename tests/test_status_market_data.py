from pathlib import Path

from app.core.config import Settings
from app.data_sources.market import FUGLE_RETRYABLE_HTTP_STATUSES, FINMIND_RETRYABLE_HTTP_STATUSES
from app.services.status_market_data import _market_data_provider_readiness


def test_market_data_status_cache_provider_and_collector_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    settings = Settings()
    service_status_source = Path("app/services/service_status.py").read_text()
    status_market_data_source = Path("app/services/status_market_data.py").read_text()

    assert status["market_data_cache"]["enabled"] is True
    assert status["market_data_cache"]["available"] == bool(status["redis"]["ok"])
    assert status["market_data_cache"]["stale_rescue_enabled"] is True
    assert status["market_data_cache"]["stale_source_marker"] == "cached-stale"
    assert status["market_data_cache"]["latest_only_source_marker"] == "latest-only"
    assert status["market_data_cache"]["price_provider_order"] == ["finmind", "fugle"]
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["live_providers"] == [
        "finmind",
        "fugle",
        "twse_tpex_openapi_latest",
    ]
    assert status["market_data_cache"]["provider_matrix"]["price_history"][
        "fallback_enabled"
    ] is True
    assert status["market_data_cache"]["provider_matrix"]["price_history"][
        "fugle_fallback_endpoints"
    ] == [
        "historical/candles",
        "historical/stats",
    ]
    assert status["market_data_cache"]["provider_matrix"]["price_history"][
        "official_openapi_latest_snapshot_fallback"
    ] is True
    assert status["market_data_cache"]["provider_matrix"]["monthly_revenue"][
        "live_providers"
    ] == [
        "finmind",
        "twse_tpex_openapi_latest",
    ]
    assert status["market_data_cache"]["provider_matrix"]["monthly_revenue"][
        "fallback_enabled"
    ] is True
    assert status["market_data_cache"]["provider_matrix"]["financial_metrics"][
        "fallback_enabled"
    ] is True
    assert (
        status["market_data_cache"]["provider_matrix"]["financial_metrics"][
            "official_openapi_scope"
        ]
        == "latest_quarter_income_balance_only"
    )
    assert (
        status["market_data_cache"]["provider_matrix"]["valuation"]["redis_cache_ttl_seconds"]
        == settings.valuation_metrics_cache_ttl_seconds
    )
    assert "TaiwanStockPER" in status["market_data_cache"]["datasets"]
    assert (
        status["market_data_cache"]["price_history_ttl_seconds"]
        == settings.price_history_cache_ttl_seconds
    )
    assert (
        status["market_data_cache"]["monthly_revenue_ttl_seconds"]
        == settings.monthly_revenue_cache_ttl_seconds
    )
    assert (
        status["market_data_cache"]["financial_metrics_ttl_seconds"]
        == settings.financial_metrics_cache_ttl_seconds
    )
    assert (
        status["market_data_cache"]["valuation_metrics_ttl_seconds"]
        == settings.valuation_metrics_cache_ttl_seconds
    )
    assert status["market_data_cache"]["official_openapi_fallback_enabled"] is True
    assert status["market_data_cache"]["official_openapi_timeout_seconds"] == 15.0
    assert status["finmind"]["collector_path"] == "app/services/status_market_data.py"
    assert status["fugle"]["collector_path"] == "app/services/status_market_data.py"
    assert status["market_data_cache"]["collector_path"] == "app/services/status_market_data.py"
    assert "from app.services.status_market_data import (" in service_status_source
    assert "def _market_data_provider_matrix(" not in service_status_source
    assert "def market_data_status(" in status_market_data_source

    assert status["finmind"]["retryable_http_statuses"] == sorted(FINMIND_RETRYABLE_HTTP_STATUSES)
    assert status["finmind"]["public_fallback_enabled"] is True
    assert status["finmind"]["data_access_ready"] is True
    assert status["finmind"]["mode"] in {"authenticated", "public_limited"}
    assert status["finmind"]["max_retries"] == settings.finmind_max_retries
    assert status["finmind"]["base_retry_delay_seconds"] == settings.finmind_base_retry_delay_seconds
    assert status["finmind"]["max_retry_delay_seconds"] == settings.finmind_max_retry_delay_seconds
    assert status["finmind"]["timeout_seconds"] == settings.finmind_timeout_seconds
    assert status["finmind"]["connect_timeout_seconds"] == settings.finmind_connect_timeout_seconds
    assert status["finmind"]["concurrency"] == settings.finmind_concurrency
    assert status["finmind"]["circuit_breaker_enabled"] == settings.finmind_circuit_breaker_enabled
    assert (
        status["finmind"]["circuit_breaker_failure_threshold"]
        == settings.finmind_circuit_breaker_failure_threshold
    )
    assert (
        status["finmind"]["circuit_breaker_recovery_seconds"]
        == settings.finmind_circuit_breaker_recovery_seconds
    )

    assert status["fugle"]["configured"] is False
    assert status["fugle"]["price_history_provider"] is True
    assert status["fugle"]["price_fallback_endpoints"] == ["historical/candles", "historical/stats"]
    assert status["fugle"]["provider_order"] == ["finmind", "fugle"]
    assert status["fugle"]["retryable_http_statuses"] == sorted(FUGLE_RETRYABLE_HTTP_STATUSES)
    assert status["fugle"]["max_retries"] == settings.fugle_max_retries
    assert status["fugle"]["base_retry_delay_seconds"] == settings.fugle_base_retry_delay_seconds
    assert status["fugle"]["max_retry_delay_seconds"] == settings.fugle_max_retry_delay_seconds
    assert status["fugle"]["timeout_seconds"] == settings.fugle_timeout_seconds
    assert status["fugle"]["connect_timeout_seconds"] == settings.fugle_connect_timeout_seconds
    assert status["fugle"]["circuit_breaker_enabled"] == settings.fugle_circuit_breaker_enabled
    assert (
        status["fugle"]["circuit_breaker_failure_threshold"]
        == settings.fugle_circuit_breaker_failure_threshold
    )
    assert (
        status["fugle"]["circuit_breaker_recovery_seconds"]
        == settings.fugle_circuit_breaker_recovery_seconds
    )


def test_market_data_provider_readiness_distinguishes_public_finmind_and_rescue_sources() -> None:
    degraded = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"]},
        {"configured": False, "public_fallback_enabled": False, "data_access_ready": False},
        {"configured": False},
    )

    assert degraded["ready"] is False
    assert degraded["finmind_authenticated"] is False
    assert degraded["finmind_public_fallback_enabled"] is False
    assert degraded["finmind_data_access_ready"] is False
    assert degraded["fugle_price_fallback_configured"] is False
    assert degraded["official_openapi_fallback_enabled"] is False
    assert degraded["official_openapi_fallback_scope"] == []
    assert "missing_finmind_access" in degraded["fallback_reason"]
    assert "missing_price_rescue_provider" in degraded["fallback_reason"]

    ready = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"]},
        {"configured": True, "public_fallback_enabled": False, "data_access_ready": True},
        {"configured": True},
    )

    assert ready["ready"] is True
    assert ready["fallback_reason"] is None

    official = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"], "official_openapi_fallback_enabled": True},
        {"configured": False, "public_fallback_enabled": True, "data_access_ready": True},
        {"configured": False},
    )

    assert official["ready"] is True
    assert official["finmind_access_mode"] == "public_limited"
    assert official["official_openapi_fallback_enabled"] is True
    assert "latest_quarter_income_balance" in official["official_openapi_fallback_scope"]
    assert "finmind_public_limited_mode_for_history_datasets" in official["warnings"]
    assert "missing_fugle_api_key_for_price_fallback" in official["warnings"]
