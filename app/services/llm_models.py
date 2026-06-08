from __future__ import annotations

from typing import Protocol


class _KeyRotator(Protocol):
    def __len__(self) -> int: ...

    def candidates(self) -> list[tuple[int, str]]: ...


def litellm_model_candidates(settings: object, preferred_model: str | None = None) -> list[str]:
    models = [litellm_model_name(preferred_model or getattr(settings, "primary_llm_model", ""))]
    raw_fallbacks = str(getattr(settings, "llm_fallback_models", "") or "")
    models.extend(
        litellm_model_name(model.strip()) for model in raw_fallbacks.split(",") if model.strip()
    )
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    if local_model:
        models.append(litellm_model_name(local_model))
    return list(dict.fromkeys(model for model in models if model))


def gemini_model_candidates(settings: object, preferred_model: str | None = None) -> list[str]:
    models = [gemini_api_model_name(preferred_model or getattr(settings, "primary_llm_model", ""))]
    raw_fallbacks = str(getattr(settings, "llm_fallback_models", "") or "")
    models.extend(
        gemini_api_model_name(model.strip()) for model in raw_fallbacks.split(",") if model.strip()
    )
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    if local_model:
        models.append(gemini_api_model_name(local_model))
    return list(
        dict.fromkeys(model for model in models if model and is_gemini_text_model_candidate(model))
    )


def gemini_vision_model_candidates(
    settings: object, preferred_model: str | None = None
) -> list[str]:
    return [
        model
        for model in gemini_model_candidates(settings, preferred_model=preferred_model)
        if is_vision_model_candidate(model)
    ]


def gemini_api_model_name(model: str | None) -> str:
    normalized = str(model or "").strip()
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    if normalized.startswith("gemini/"):
        normalized = normalized.removeprefix("gemini/")
    return normalized


def is_gemini_text_model_candidate(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    if not normalized.startswith(("gemini", "gemma")):
        return False
    return not any(
        blocked in normalized
        for blocked in ("embedding", "imagen", "image", "live", "tts", "audio")
    )


def is_vision_model_candidate(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    if normalized.startswith(("models/", "gemini/")):
        normalized = normalized.split("/", 1)[1]
    if normalized.startswith("gemma"):
        return False
    return (
        normalized.startswith("gemini")
        or normalized.startswith("gpt-")
        or normalized.startswith("openai/")
        or normalized.startswith("claude")
        or normalized.startswith("anthropic/")
    ) and not any(
        blocked in normalized
        for blocked in ("embedding", "imagen", "image", "live", "tts", "audio")
    )


def litellm_model_name(model: str) -> str:
    normalized = str(model or "").strip()
    if not normalized or "/" in normalized:
        return normalized
    if normalized.startswith(("gemini", "gemma")):
        return f"gemini/{normalized}"
    if normalized.startswith("claude"):
        return f"anthropic/{normalized}"
    return normalized


def litellm_key_candidates(
    model: str,
    settings: object,
    rotator: _KeyRotator,
) -> list[tuple[int | None, str | None]]:
    normalized = str(model or "").strip().lower()
    if (normalized.startswith("gemini/") or normalized.startswith("gemma")) and len(rotator) > 0:
        return rotator.candidates()
    if normalized.startswith("openai/") or normalized.startswith("gpt-"):
        api_key = getattr(settings, "openai_api_key", None)
        return [(None, api_key)] if api_key else [(None, None)]
    if normalized.startswith("anthropic/") or normalized.startswith("claude"):
        api_key = getattr(settings, "anthropic_api_key", None)
        return [(None, api_key)] if api_key else [(None, None)]
    return [(None, None)]


def litellm_model_requires_api_key(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return (
        normalized.startswith("gemini/")
        or normalized.startswith("gemma")
        or normalized.startswith("openai/")
        or normalized.startswith("gpt-")
        or normalized.startswith("anthropic/")
        or normalized.startswith("claude")
    )


def model_quota_cooldown_key(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    if normalized.startswith("gemini/"):
        normalized = normalized.removeprefix("gemini/")
    return normalized
