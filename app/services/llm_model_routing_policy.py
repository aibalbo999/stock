from __future__ import annotations


SMART_FIRST_FLASH_MODELS = (
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
)
HIGH_QUOTA_TEXT_FALLBACK_MODEL = "gemma-4-31b-it"
REPORT_ROUTE_MEDIA_MODEL_MARKERS = ("imagen", "live")


def configured_text_model_order(settings: object) -> list[str]:
    primary = str(getattr(settings, "primary_llm_model", "") or "").strip()
    fallback_models = split_config_values(str(getattr(settings, "llm_fallback_models", "") or ""))
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    return list(
        dict.fromkeys(
            model
            for model in [primary, *fallback_models, local_model]
            if str(model or "").strip()
        )
    )


def effective_fallback_models(settings: object) -> list[str]:
    models = split_config_values(str(getattr(settings, "llm_fallback_models", "") or ""))
    provider = str(getattr(settings, "llm_provider", "") or "").lower().replace("-", "_")
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    if provider == "litellm" and local_model:
        models.append(local_model)
    primary = str(getattr(settings, "primary_llm_model", "") or "").strip()
    return list(dict.fromkeys(model for model in models if model and model != primary))


def llm_model_provider(model: str) -> str:
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


def report_route_media_or_live_models(model_order: list[str], normalize_model_func) -> list[str]:
    return [
        model
        for model in model_order
        if any(
            marker in normalize_model_func(model)
            for marker in REPORT_ROUTE_MEDIA_MODEL_MARKERS
        )
    ]


def split_config_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def normalize_model_name(model: str) -> str:
    normalized = str(model or "").strip().lower()
    for prefix in ("models/", "gemini/", "google/"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
    return normalized


__all__ = [
    "HIGH_QUOTA_TEXT_FALLBACK_MODEL",
    "REPORT_ROUTE_MEDIA_MODEL_MARKERS",
    "SMART_FIRST_FLASH_MODELS",
    "configured_text_model_order",
    "effective_fallback_models",
    "llm_model_provider",
    "normalize_model_name",
    "report_route_media_or_live_models",
    "split_config_values",
]
