from types import SimpleNamespace

from app.services.api_key_rotation import APIKeyRotator
from app.services.llm_models import (
    gemini_model_candidates,
    gemini_vision_model_candidates,
    litellm_key_candidates,
    litellm_model_name,
)


def fake_settings(**overrides) -> SimpleNamespace:
    defaults = {
        "primary_llm_model": "gemini-test",
        "llm_fallback_models": "",
        "local_llm_model": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_gemini_model_candidates_filter_non_text_models_and_normalize_names() -> None:
    settings = fake_settings(
        primary_llm_model="models/gemini-3.5-flash",
        llm_fallback_models=(
            "gemini-embedding-2,imagen-4.0-generate-001,"
            "gemini-3.1-flash-live-preview,gemini-2.5-flash,"
            "gemma-4-31b-it,gemini-3.1-flash-lite,gemini-2.5-flash-lite"
        ),
        local_llm_model="gemma-4-31b-it",
    )

    assert gemini_model_candidates(settings) == [
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemma-4-31b-it",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
    ]
    assert gemini_vision_model_candidates(settings) == [
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
    ]


def test_litellm_model_name_normalizes_gemini_only() -> None:
    assert litellm_model_name("gemini-2.5-flash") == "gemini/gemini-2.5-flash"
    assert litellm_model_name("gemini/gemini-2.5-flash") == "gemini/gemini-2.5-flash"
    assert litellm_model_name("claude-3-5-haiku") == "anthropic/claude-3-5-haiku"
    assert litellm_model_name("anthropic/claude-3-5-haiku") == "anthropic/claude-3-5-haiku"
    assert litellm_model_name("gpt-4o-mini") == "gpt-4o-mini"
    assert litellm_model_name("gemma-4-31b-it") == "gemini/gemma-4-31b-it"


def test_litellm_key_candidates_support_openai_and_anthropic_keys() -> None:
    settings = fake_settings(openai_api_key="openai-key", anthropic_api_key="anthropic-key")
    rotator = APIKeyRotator(["gemini-key"])

    assert litellm_key_candidates("gpt-4o-mini", settings, rotator) == [(None, "openai-key")]
    assert litellm_key_candidates("openai/gpt-4o-mini", settings, rotator) == [(None, "openai-key")]
    assert litellm_key_candidates("anthropic/claude-3-5-haiku", settings, rotator) == [
        (None, "anthropic-key")
    ]
    assert litellm_key_candidates("gemma-4-31b-it", settings, rotator) == [(0, "gemini-key")]
