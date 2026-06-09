from __future__ import annotations

from app.services.llm_quota import (
    FREE_TIER_RATE_LIMIT_SOURCE,
    FREE_TIER_REQUEST_BUDGET_REFERENCES,
    normalize_model_name,
    parse_model_budget_map,
)

SMART_FIRST_FLASH_MODELS = (
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
)
HIGH_QUOTA_TEXT_FALLBACK_MODEL = "gemma-4-31b-it"
REPORT_ROUTE_MEDIA_MODEL_MARKERS = ("imagen", "live")


def _llm_fallback_readiness(fallback_models: list[str], provider_keys: dict) -> list[dict]:
    rows = []
    for model in fallback_models:
        provider = _llm_model_provider(model)
        key_configured = bool(provider_keys.get(provider)) if provider in provider_keys else None
        rows.append(
            {
                "model": model,
                "provider": provider,
                "key_configured": key_configured,
            }
        )
    return rows


def _llm_model_provider(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if normalized.startswith(("gemini", "gemma")) or normalized.startswith("google/"):
        return "gemini"
    if normalized.startswith("anthropic/") or normalized.startswith("claude"):
        return "anthropic"
    if normalized.startswith("openai/") or normalized.startswith("gpt-"):
        return "openai"
    if normalized.startswith(("ollama/", "lm_studio/", "local/")):
        return "local"
    return "unknown"


def _llm_effective_fallback_models(settings) -> list[str]:
    models = [
        model.strip()
        for model in str(settings.llm_fallback_models or "").split(",")
        if model.strip()
    ]
    provider = str(getattr(settings, "llm_provider", "") or "").lower().replace("-", "_")
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    if provider == "litellm" and local_model:
        models.append(local_model)
    primary = str(getattr(settings, "primary_llm_model", "") or "").strip()
    return list(dict.fromkeys(model for model in models if model and model != primary))


def _llm_quota_routing_status(settings) -> dict:
    primary_model = str(getattr(settings, "primary_llm_model", "") or "").strip()
    fallback_models = _split_config_values(str(getattr(settings, "llm_fallback_models", "") or ""))
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    model_order = list(
        dict.fromkeys(
            model
            for model in [primary_model, *fallback_models, local_model]
            if str(model or "").strip()
        )
    )
    normalized_order = [normalize_model_name(model) for model in model_order]
    smart_order = [normalize_model_name(model) for model in SMART_FIRST_FLASH_MODELS]
    high_quota_model_key = normalize_model_name(HIGH_QUOTA_TEXT_FALLBACK_MODEL)
    request_budgets = parse_model_budget_map(
        getattr(settings, "llm_model_daily_request_budgets", "")
    )
    smart_request_budgets = {model: request_budgets.get(model) for model in smart_order}
    smart_budget_values = [
        int(budget) for budget in smart_request_budgets.values() if budget is not None
    ]
    smart_model_request_budgets_configured = (
        len(smart_budget_values) == len(smart_order)
        and all(budget > 0 for budget in smart_budget_values)
    )
    official_smart_request_budgets = {
        model: FREE_TIER_REQUEST_BUDGET_REFERENCES[model]
        for model in smart_order
        if model in FREE_TIER_REQUEST_BUDGET_REFERENCES
    }
    official_smart_request_budgets_match = all(
        request_budgets.get(model) == official_budget
        for model, official_budget in official_smart_request_budgets.items()
    )
    max_smart_budget = max(smart_budget_values) if smart_budget_values else None
    high_quota_budget = request_budgets.get(high_quota_model_key)
    smart_model_order_ready = normalized_order[: len(smart_order)] == smart_order
    high_quota_fallback_present = high_quota_model_key in normalized_order
    if high_quota_fallback_present:
        high_quota_rank = normalized_order.index(high_quota_model_key) + 1
        high_quota_after_smart_models = all(
            model in normalized_order and normalized_order.index(high_quota_model_key) > normalized_order.index(model)
            for model in smart_order
        )
    else:
        high_quota_rank = None
        high_quota_after_smart_models = False
    high_quota_budget_ready = bool(
        high_quota_budget is not None
        and max_smart_budget is not None
        and high_quota_budget > max_smart_budget
        and high_quota_budget >= 1000
    )
    hard_routing_enabled = bool(getattr(settings, "llm_quota_hard_routing_enabled", True))
    cooldown_seconds = max(0.0, float(getattr(settings, "llm_model_quota_cooldown_seconds", 0.0)))
    quota_timezone = str(getattr(settings, "llm_quota_window_timezone", "") or "").strip()
    quota_warning_ratio = _safe_warning_ratio(getattr(settings, "llm_quota_warning_ratio", 0.8))
    media_or_live_models = [
        model
        for model in model_order
        if any(marker in normalize_model_name(model) for marker in REPORT_ROUTE_MEDIA_MODEL_MARKERS)
    ]
    embedding_model_key = normalize_model_name(getattr(settings, "rag_embedding_model", ""))
    checks = {
        "primary_model_preserved": normalized_order[:1] == smart_order[:1],
        "smart_model_order": smart_model_order_ready,
        "required_text_models_configured": all(
            model in normalized_order for model in [*smart_order, high_quota_model_key]
        ),
        "smart_model_request_budgets_configured": smart_model_request_budgets_configured,
        "high_quota_fallback_after_smart_models": high_quota_after_smart_models,
        "high_quota_fallback_budget_ready": high_quota_budget_ready,
        "hard_routing_enabled": hard_routing_enabled,
        "quota_cooldown_enabled": cooldown_seconds > 0,
        "quota_window_timezone_configured": bool(quota_timezone),
        "quota_warning_ratio_configured": 0.0 < quota_warning_ratio < 1.0,
        "embedding_model_kept_separate": embedding_model_key == "gemini-embedding-2",
        "media_live_models_excluded_from_report_route": not media_or_live_models,
    }
    failed_checks = [name for name, ok in checks.items() if not ok]
    return {
        "collector_path": "app/services/status_llm.py",
        "ready": not failed_checks,
        "strategy": "smartest_first_then_budget_degrade",
        "selection_rule": "Use the first configured model that is not exhausted in the current quota window.",
        "quota_endpoint": "GET /llm/quota",
        "primary_model": primary_model,
        "fallback_models": fallback_models,
        "local_llm_model": local_model,
        "model_order": model_order,
        "normalized_model_order": normalized_order,
        "expected_smart_order": list(SMART_FIRST_FLASH_MODELS),
        "high_quota_text_fallback_model": HIGH_QUOTA_TEXT_FALLBACK_MODEL,
        "high_quota_text_fallback_rank": high_quota_rank,
        "hard_routing_enabled": hard_routing_enabled,
        "quota_cooldown_seconds": cooldown_seconds,
        "quota_window_timezone": quota_timezone,
        "quota_warning_ratio": quota_warning_ratio,
        "smart_model_request_budgets": smart_request_budgets,
        "official_free_tier_request_budget_references": official_smart_request_budgets,
        "official_free_tier_request_budgets_match": official_smart_request_budgets_match,
        "official_free_tier_budget_drift": {
            model: {
                "configured": request_budgets.get(model),
                "official_free_tier_reference": official_budget,
            }
            for model, official_budget in official_smart_request_budgets.items()
            if request_budgets.get(model) != official_budget
        },
        "free_tier_rate_limit_source": FREE_TIER_RATE_LIMIT_SOURCE,
        "high_quota_fallback_request_budget": high_quota_budget,
        "configured_request_budget_models": sorted(request_budgets),
        "budget_source": "LLM_MODEL_DAILY_REQUEST_BUDGETS",
        "budget_scope_note": (
            "Budgets are project-configured daily request limits; update them to match the "
            "current Google AI Studio project limits for the deployed key/project."
        ),
        "embedding_model": getattr(settings, "rag_embedding_model", ""),
        "excluded_media_live_models": media_or_live_models,
        "readiness_checks": checks,
        "failed_checks": failed_checks,
    }


def _split_config_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _safe_warning_ratio(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.8
    if parsed <= 0 or parsed >= 1:
        return 0.8
    return parsed
