from __future__ import annotations

from app.data_sources.market import (
    FUGLE_RETRYABLE_HTTP_STATUSES,
    FINMIND_RETRYABLE_HTTP_STATUSES,
    MarketDataClient,
)


def market_data_status(settings, *, redis_status: dict) -> dict:
    return {
        "finmind": _finmind_status(settings),
        "fugle": _fugle_status(settings),
        "market_data_cache": _market_data_cache_status(
            settings,
            redis_status=redis_status,
        ),
    }


def _finmind_status(settings) -> dict:
    configured = bool(settings.finmind_token)
    public_fallback_enabled = bool(settings.finmind_public_fallback_enabled)
    return {
        "collector_path": "app/services/status_market_data.py",
        "configured": configured,
        "public_fallback_enabled": public_fallback_enabled,
        "data_access_ready": bool(configured or public_fallback_enabled),
        "mode": (
            "authenticated"
            if configured
            else "public_limited"
            if public_fallback_enabled
            else "disabled"
        ),
        "retryable_http_statuses": sorted(FINMIND_RETRYABLE_HTTP_STATUSES),
        "max_retries": max(0, int(settings.finmind_max_retries)),
        "base_retry_delay_seconds": max(0.0, float(settings.finmind_base_retry_delay_seconds)),
        "max_retry_delay_seconds": max(0.0, float(settings.finmind_max_retry_delay_seconds)),
        "timeout_seconds": max(1.0, float(settings.finmind_timeout_seconds)),
        "connect_timeout_seconds": max(1.0, float(settings.finmind_connect_timeout_seconds)),
        "concurrency": max(1, int(settings.finmind_concurrency)),
        "circuit_breaker_enabled": bool(settings.finmind_circuit_breaker_enabled),
        "circuit_breaker_failure_threshold": max(
            1,
            int(settings.finmind_circuit_breaker_failure_threshold),
        ),
        "circuit_breaker_recovery_seconds": max(
            0.0,
            float(settings.finmind_circuit_breaker_recovery_seconds),
        ),
    }


def _fugle_status(settings) -> dict:
    return {
        "collector_path": "app/services/status_market_data.py",
        "configured": bool(settings.fugle_api_key),
        "price_history_provider": True,
        "price_fallback_endpoints": ["historical/candles", "historical/stats"],
        "provider_order": _split_config_values(settings.market_price_provider_order),
        "retryable_http_statuses": sorted(FUGLE_RETRYABLE_HTTP_STATUSES),
        "max_retries": max(0, int(settings.fugle_max_retries)),
        "base_retry_delay_seconds": max(0.0, float(settings.fugle_base_retry_delay_seconds)),
        "max_retry_delay_seconds": max(0.0, float(settings.fugle_max_retry_delay_seconds)),
        "timeout_seconds": max(1.0, float(settings.fugle_timeout_seconds)),
        "connect_timeout_seconds": max(1.0, float(settings.fugle_connect_timeout_seconds)),
        "circuit_breaker_enabled": bool(settings.fugle_circuit_breaker_enabled),
        "circuit_breaker_failure_threshold": max(
            1,
            int(settings.fugle_circuit_breaker_failure_threshold),
        ),
        "circuit_breaker_recovery_seconds": max(
            0.0,
            float(settings.fugle_circuit_breaker_recovery_seconds),
        ),
    }


def _market_data_cache_status(settings, *, redis_status: dict) -> dict:
    return {
        "collector_path": "app/services/status_market_data.py",
        "enabled": settings.market_data_cache_enabled,
        "available": bool(settings.market_data_cache_enabled and redis_status.get("ok")),
        "backend": "redis",
        "stale_rescue_enabled": True,
        "stale_source_marker": MarketDataClient.STALE_CACHE_SOURCE_MARKER,
        "latest_only_source_marker": MarketDataClient.LATEST_ONLY_SOURCE_MARKER,
        "price_provider_order": _split_config_values(settings.market_price_provider_order),
        "provider_matrix": _market_data_provider_matrix(settings),
        "datasets": [
            "TaiwanStockPrice",
            "TaiwanStockMonthRevenue",
            "TaiwanStockFinancialStatements",
            "TaiwanStockBalanceSheet",
            "TaiwanStockCashFlowsStatement",
            "TaiwanStockPER",
        ],
        "price_history_ttl_seconds": settings.price_history_cache_ttl_seconds,
        "monthly_revenue_ttl_seconds": settings.monthly_revenue_cache_ttl_seconds,
        "financial_metrics_ttl_seconds": settings.financial_metrics_cache_ttl_seconds,
        "valuation_metrics_ttl_seconds": settings.valuation_metrics_cache_ttl_seconds,
        "official_openapi_fallback_enabled": settings.market_official_openapi_fallback_enabled,
        "official_openapi_timeout_seconds": settings.market_official_openapi_timeout_seconds,
    }


def _market_data_provider_matrix(settings) -> dict:
    price_provider_order = _split_config_values(settings.market_price_provider_order)
    finmind_configured = bool(settings.finmind_token)
    finmind_public_fallback_enabled = bool(settings.finmind_public_fallback_enabled)
    finmind_ready = bool(finmind_configured or finmind_public_fallback_enabled)
    finmind_provider_label = "finmind_authenticated" if finmind_configured else "finmind_public_limited"
    fugle_configured = bool(settings.fugle_api_key)
    official_openapi_enabled = bool(settings.market_official_openapi_fallback_enabled)
    official_provider = "twse_tpex_openapi_latest"
    price_live_providers = list(price_provider_order or ["finmind"])
    if official_openapi_enabled and official_provider not in price_live_providers:
        price_live_providers.append(official_provider)
    return {
        "price_history": {
            "label": "股價歷史",
            "live_providers": price_live_providers,
            "fallback_enabled": "fugle" in price_provider_order,
            "fallback_configured": bool("fugle" in price_provider_order and fugle_configured),
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready and "finmind" in price_live_providers),
                    ("fugle", fugle_configured and "fugle" in price_live_providers),
                    (official_provider, official_openapi_enabled and official_provider in price_live_providers),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fugle_fallback_endpoints": ["historical/candles", "historical/stats"],
            "official_openapi_latest_snapshot_fallback": official_openapi_enabled,
            "redis_cache_ttl_seconds": settings.price_history_cache_ttl_seconds,
        },
        "monthly_revenue": {
            "label": "月營收",
            "live_providers": ["finmind", official_provider],
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready),
                    (official_provider, official_openapi_enabled),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fallback_enabled": official_openapi_enabled,
            "fallback_configured": official_openapi_enabled,
            "official_openapi_scope": "latest_reported_month_only",
            "redis_cache_ttl_seconds": settings.monthly_revenue_cache_ttl_seconds,
        },
        "financial_metrics": {
            "label": "五年財務",
            "live_providers": ["finmind", official_provider],
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready),
                    (official_provider, official_openapi_enabled),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fallback_enabled": official_openapi_enabled,
            "fallback_configured": official_openapi_enabled,
            "official_openapi_scope": "latest_quarter_income_balance_only",
            "redis_cache_ttl_seconds": settings.financial_metrics_cache_ttl_seconds,
        },
        "valuation": {
            "label": "估值",
            "live_providers": ["finmind", official_provider],
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready),
                    (official_provider, official_openapi_enabled),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fallback_enabled": official_openapi_enabled,
            "fallback_configured": official_openapi_enabled,
            "official_openapi_scope": "latest_daily_valuation_only",
            "redis_cache_ttl_seconds": settings.valuation_metrics_cache_ttl_seconds,
        },
    }


def _market_data_provider_readiness(
    market_cache_status: dict,
    finmind_status: dict,
    fugle_status: dict,
) -> dict:
    provider_order = market_cache_status.get("price_provider_order") or []
    finmind_configured = bool(finmind_status.get("configured"))
    finmind_public_fallback_enabled = bool(finmind_status.get("public_fallback_enabled"))
    finmind_data_ready = bool(finmind_status.get("data_access_ready") or finmind_configured)
    fugle_configured = bool(fugle_status.get("configured"))
    official_openapi_enabled = bool(market_cache_status.get("official_openapi_fallback_enabled"))
    price_fallback_declared = "fugle" in provider_order
    price_fallback_configured = bool(price_fallback_declared and fugle_configured)
    price_rescue_configured = bool(price_fallback_configured or official_openapi_enabled)
    finmind_only_datasets = []
    blockers = []
    warnings = []
    if not finmind_data_ready:
        blockers.append("missing_finmind_access_for_monthly_revenue_financials_valuation")
    elif not finmind_configured and finmind_public_fallback_enabled:
        warnings.append("finmind_public_limited_mode_for_history_datasets")
    if price_fallback_declared and not fugle_configured:
        warnings.append("missing_fugle_api_key_for_price_fallback")
    if not price_fallback_declared:
        warnings.append("price_provider_order_lacks_fugle_fallback")
    if not price_rescue_configured:
        blockers.append("missing_price_rescue_provider")
    return {
        "ready": bool(finmind_data_ready and price_rescue_configured),
        "finmind_authenticated": finmind_configured,
        "finmind_public_fallback_enabled": finmind_public_fallback_enabled,
        "finmind_data_access_ready": finmind_data_ready,
        "finmind_access_mode": "authenticated"
        if finmind_configured
        else "public_limited"
        if finmind_public_fallback_enabled
        else "disabled",
        "fugle_price_fallback_configured": price_fallback_configured,
        "price_fallback_declared": price_fallback_declared,
        "price_rescue_configured": price_rescue_configured,
        "price_rescue_modes": [
            mode
            for mode, configured in (
                ("fugle_history", price_fallback_configured),
                ("official_openapi_latest_snapshot", official_openapi_enabled),
            )
            if configured
        ],
        "official_openapi_fallback_enabled": official_openapi_enabled,
        "official_openapi_fallback_scope": [
            "latest_price_snapshot",
            "latest_monthly_revenue",
            "latest_quarter_income_balance",
            "latest_daily_valuation",
        ]
        if official_openapi_enabled
        else [],
        "finmind_only_datasets": finmind_only_datasets,
        "full_history_datasets_requiring_finmind": [
            "monthly_revenue_history",
            "five_year_financial_metrics",
            "valuation_history",
        ],
        "official_openapi_latest_only_datasets": [
            "latest_price_snapshot",
            "latest_monthly_revenue",
            "latest_quarter_income_balance",
            "latest_daily_valuation",
        ]
        if official_openapi_enabled
        else [],
        "finmind_only_datasets_ready": finmind_data_ready,
        "warnings": warnings,
        "fallback_reason": ";".join(blockers) if blockers else None,
    }


def _split_config_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
