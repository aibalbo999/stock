from __future__ import annotations

import httpx

from app.data_sources import market_provider_runtime


def finmind_timeout(settings) -> httpx.Timeout:
    return httpx.Timeout(
        max(1.0, float(getattr(settings, "finmind_timeout_seconds", 20.0))),
        connect=max(1.0, float(getattr(settings, "finmind_connect_timeout_seconds", 8.0))),
    )


def fugle_timeout(settings) -> httpx.Timeout:
    return httpx.Timeout(
        max(1.0, float(getattr(settings, "fugle_timeout_seconds", 20.0))),
        connect=max(1.0, float(getattr(settings, "fugle_connect_timeout_seconds", 8.0))),
    )


def official_openapi_timeout(settings) -> httpx.Timeout:
    timeout_seconds = max(
        1.0,
        float(getattr(settings, "market_official_openapi_timeout_seconds", 15.0)),
    )
    return httpx.Timeout(
        timeout_seconds,
        connect=max(1.0, min(8.0, timeout_seconds)),
    )


def provider_circuit_breakers(
    settings,
) -> dict[str, market_provider_runtime.ProviderCircuitBreaker]:
    return {
        "finmind": market_provider_runtime.ProviderCircuitBreaker(
            "FinMind",
            enabled=provider_circuit_setting(settings, "finmind", "enabled", True),
            failure_threshold=provider_circuit_setting(
                settings,
                "finmind",
                "failure_threshold",
                5,
            ),
            recovery_seconds=provider_circuit_setting(
                settings,
                "finmind",
                "recovery_seconds",
                60.0,
            ),
        ),
        "fugle": market_provider_runtime.ProviderCircuitBreaker(
            "Fugle",
            enabled=provider_circuit_setting(settings, "fugle", "enabled", True),
            failure_threshold=provider_circuit_setting(
                settings,
                "fugle",
                "failure_threshold",
                5,
            ),
            recovery_seconds=provider_circuit_setting(
                settings,
                "fugle",
                "recovery_seconds",
                60.0,
            ),
        ),
    }


def provider_circuit_setting(settings, provider: str, suffix: str, default):
    return market_provider_runtime.provider_circuit_setting(
        settings,
        provider,
        suffix,
        default,
    )


def market_price_provider_order(settings) -> list[str]:
    return market_provider_runtime.market_price_provider_order(
        getattr(settings, "market_price_provider_order", "finmind,fugle")
    )


def finmind_max_retries(settings) -> int:
    return max(0, int(getattr(settings, "finmind_max_retries", 2)))


def finmind_base_retry_delay_seconds(settings) -> float:
    return max(0.0, float(getattr(settings, "finmind_base_retry_delay_seconds", 0.5)))


def finmind_max_retry_delay_seconds(settings) -> float:
    return max(0.0, float(getattr(settings, "finmind_max_retry_delay_seconds", 5.0)))


def finmind_public_fallback_enabled(settings) -> bool:
    return bool(getattr(settings, "finmind_public_fallback_enabled", True))


def fugle_api_key(settings) -> str:
    return str(getattr(settings, "fugle_api_key", "") or "").strip()


def fugle_max_retries(settings) -> int:
    return max(0, int(getattr(settings, "fugle_max_retries", 2)))


def fugle_base_retry_delay_seconds(settings) -> float:
    return max(0.0, float(getattr(settings, "fugle_base_retry_delay_seconds", 0.5)))


def fugle_max_retry_delay_seconds(settings) -> float:
    return max(0.0, float(getattr(settings, "fugle_max_retry_delay_seconds", 5.0)))


def official_openapi_fallback_enabled(settings) -> bool:
    return bool(getattr(settings, "market_official_openapi_fallback_enabled", True))
