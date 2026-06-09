from __future__ import annotations

from app.services.llm_model_routing_policy import normalize_model_name

FREE_TIER_RATE_LIMIT_SOURCE = {
    "provider": "Google Gemini API rate limits",
    "url": "https://ai.google.dev/gemini-api/docs/rate-limits",
    "last_reviewed": "2026-06-09",
    "tier": "Free",
    "scope": "project_level",
    "reset_timezone": "America/Los_Angeles",
    "note": (
        "Published limits are references only; the active project limits shown in "
        "Google AI Studio remain authoritative."
    ),
}
FREE_TIER_REQUEST_BUDGET_REFERENCES = {
    "gemini-2.5-flash": 250,
    "gemini-2.5-flash-preview": 250,
    "gemini-2.5-flash-lite": 1000,
    "gemini-2.5-flash-lite-preview": 1000,
    "gemini-2.0-flash": 200,
    "gemini-2.0-flash-lite": 200,
    "gemini-embedding-2": 1000,
    "gemini-embedding": 1000,
    "gemma-3": 14400,
    "gemma-3n": 14400,
}
FREE_TIER_TOKEN_BUDGET_REFERENCES = {
    "gemini-2.5-flash": 250_000,
    "gemini-2.5-flash-preview": 250_000,
    "gemini-2.5-flash-lite": 250_000,
    "gemini-2.5-flash-lite-preview": 250_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-2.0-flash-lite": 1_000_000,
    "gemini-embedding-2": 30_000,
    "gemini-embedding": 30_000,
    "gemma-3": 15_000,
    "gemma-3n": 15_000,
}
PROJECT_CONFIGURED_MODEL_BUDGET_NOTES = {
    "gemini-3.5-flash": (
        "Preserved as the user-confirmed smartest first model; no public Free Tier row was "
        "found in the reviewed Gemini API rate-limit table, so the configured budget should "
        "match this project in Google AI Studio."
    ),
    "gemini-3.1-flash-lite": (
        "Preserved as a user-confirmed fallback model; no public Free Tier row was found in "
        "the reviewed Gemini API rate-limit table, so the configured budget should match "
        "this project in Google AI Studio."
    ),
    "gemma-4-31b-it": (
        "Preserved as the high-volume Gemma fallback configured for this project. Public "
        "Gemini API Free Tier tables list Gemma 3/3n at 14,400 RPD; confirm this exact "
        "model's active limit in Google AI Studio."
    ),
}


def parse_model_budget_map(raw: str | None) -> dict[str, int]:
    budgets: dict[str, int] = {}
    for item in str(raw or "").split(","):
        if "=" not in item:
            continue
        model, value = item.split("=", 1)
        model_key = normalize_model_name(model)
        try:
            parsed = int(float(value.strip()))
        except (TypeError, ValueError):
            continue
        if model_key and parsed > 0:
            budgets[model_key] = parsed
    return budgets


def quota_reference_source(
    model_key: str,
    *,
    unreferenced_source: str = "configured_budget_only",
) -> str:
    if model_key in FREE_TIER_REQUEST_BUDGET_REFERENCES:
        return "google_free_tier_reference"
    if model_key in PROJECT_CONFIGURED_MODEL_BUDGET_NOTES:
        return "project_configured_ai_studio_limit"
    return unreferenced_source


def quota_reference_note(
    model_key: str,
    *,
    free_tier_note: str | None = None,
    unreferenced_note: str = (
        "No built-in Free Tier reference is available; keep the configured budget aligned "
        "with Google AI Studio."
    ),
) -> str:
    if model_key in FREE_TIER_REQUEST_BUDGET_REFERENCES:
        return (
            free_tier_note
            if free_tier_note is not None
            else "Published Google Gemini API Free Tier reference for this model family."
        )
    return PROJECT_CONFIGURED_MODEL_BUDGET_NOTES.get(model_key, unreferenced_note)


__all__ = [
    "FREE_TIER_RATE_LIMIT_SOURCE",
    "FREE_TIER_REQUEST_BUDGET_REFERENCES",
    "FREE_TIER_TOKEN_BUDGET_REFERENCES",
    "PROJECT_CONFIGURED_MODEL_BUDGET_NOTES",
    "parse_model_budget_map",
    "quota_reference_note",
    "quota_reference_source",
]
