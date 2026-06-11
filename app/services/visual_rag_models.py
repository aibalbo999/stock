from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.services.llm_quota import normalize_model_name, parse_model_budget_map


def visual_rag_model(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    configured_model = str(settings.company_filing_visual_rag_model or "").strip()
    return configured_model or str(settings.primary_llm_model)


def visual_rag_model_chain(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    preferred_model = visual_rag_model(settings)
    fallback_models = _split_model_list(getattr(settings, "llm_fallback_models", ""))
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    configured_models = list(
        dict.fromkeys(
            model
            for model in [preferred_model, *fallback_models, local_model]
            if str(model or "").strip()
        )
    )
    request_budgets = parse_model_budget_map(
        getattr(settings, "llm_model_daily_request_budgets", "")
    )
    token_budgets = parse_model_budget_map(getattr(settings, "llm_model_daily_token_budgets", ""))
    rows: list[dict[str, Any]] = []
    vision_candidates: list[dict[str, Any]] = []
    rejected_candidates: list[dict[str, Any]] = []
    for rank, configured_model in enumerate(configured_models, start=1):
        model_key = normalize_model_name(configured_model)
        request_budget = request_budgets.get(model_key)
        vision_supported = is_visual_rag_model_candidate(configured_model)
        row: dict[str, Any] = {
            "rank": rank,
            "model": configured_model,
            "model_key": model_key,
            "vision_supported": vision_supported,
            "key_configured": (
                vision_model_key_configured(configured_model, settings)
                if vision_supported
                else None
            ),
            "request_budget": request_budget,
            "token_budget": token_budgets.get(model_key),
            "routing_tier": visual_rag_routing_tier(
                rank=rank,
                model_key=model_key,
                request_budget=request_budget,
            ),
        }
        rows.append(row)
        if vision_supported:
            vision_candidates.append(row)
        else:
            rejected_row = {
                **row,
                "rejection_reason": visual_rag_model_rejection_reason(configured_model),
            }
            rejected_candidates.append(rejected_row)

    provider = str(settings.llm_provider or "gemini_http").strip().lower().replace("-", "_")
    provider_compatible_vision_candidates = [
        {
            **candidate,
            "provider_compatible": True,
            "selection_reason": (
                "preferred_visual_rag_model"
                if int(candidate.get("rank") or 0) == 1
                else "fallback_visual_rag_model"
            ),
        }
        for candidate in vision_candidates
        if visual_rag_provider_can_call_model(
            str(candidate.get("model") or ""),
            provider=provider,
        )
    ]

    return {
        "strategy": "smartest_first_then_budget_degrade_for_vision_capable_models",
        "selection_rule": (
            "先使用已設定的 Visual RAG 模型，再依序嘗試 LLM 後援；"
            "執行前會排除純文字、媒體、embedding 與 live 模型。"
        ),
        "quota_hard_routing_enabled": bool(
            getattr(settings, "llm_quota_hard_routing_enabled", True)
        ),
        "quota_cooldown_seconds": max(
            0.0,
            float(getattr(settings, "llm_model_quota_cooldown_seconds", 0.0)),
        ),
        "quota_endpoint": "GET /llm/quota",
        "budget_source": "LLM_MODEL_DAILY_REQUEST_BUDGETS",
        "configured_models": configured_models,
        "candidate_rows": rows,
        "vision_candidates": vision_candidates,
        "vision_candidate_models": [item["model"] for item in vision_candidates],
        "provider_compatible_vision_candidates": provider_compatible_vision_candidates,
        "provider_compatible_vision_candidate_models": [
            item["model"] for item in provider_compatible_vision_candidates
        ],
        "rejected_candidates": rejected_candidates,
        "excluded_non_vision_models": [item["model"] for item in rejected_candidates],
    }


def vision_model_key_configured(model: str, settings: Settings) -> bool:
    normalized = canonical_visual_rag_model_name(model)
    if not normalized:
        return False
    if normalized.startswith(("gemini", "gemma", "google/")):
        return len(settings.gemini_api_keys) > 0
    if normalized.startswith(("openai/", "gpt-")):
        return bool(settings.openai_api_key)
    if normalized.startswith(("anthropic/", "claude")):
        return bool(settings.anthropic_api_key)
    if normalized.startswith(("ollama/", "lm_studio/", "local/")):
        return True
    return bool(
        len(settings.gemini_api_keys) > 0 or settings.openai_api_key or settings.anthropic_api_key
    )


def visual_rag_runtime_candidate(
    *,
    model_chain: dict[str, Any],
) -> dict[str, Any]:
    compatible_candidates = [
        candidate
        for candidate in model_chain.get("provider_compatible_vision_candidates") or []
        if isinstance(candidate, dict)
    ]
    for candidate in compatible_candidates:
        if candidate.get("key_configured"):
            return candidate
    return {
        "model": None,
        "key_configured": False,
        "provider_compatible": False,
        "selection_reason": "no_provider_compatible_vision_model_with_key",
    }


def visual_rag_provider_can_call_model(model: str, *, provider: str) -> bool:
    normalized_provider = str(provider or "").strip().lower().replace("-", "_")
    normalized_model = canonical_visual_rag_model_name(model)
    if normalized_provider == "litellm":
        return True
    if normalized_provider in {"gemini_http", "google_genai"}:
        return normalized_model.startswith("gemini")
    return normalized_model.startswith(("ollama/", "lm_studio/", "local/"))


def is_visual_rag_model_candidate(model: str) -> bool:
    normalized = canonical_visual_rag_model_name(model)
    if normalized.startswith("gemma"):
        return False
    if not normalized.startswith(("gemini", "gpt-", "openai/", "claude", "anthropic/")):
        return False
    return not any(
        blocked in normalized
        for blocked in ("embedding", "imagen", "image", "live", "tts", "audio")
    )


def canonical_visual_rag_model_name(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if normalized.startswith(("models/", "gemini/", "google/")):
        return normalized.split("/", 1)[1]
    return normalized


def visual_rag_model_rejection_reason(model: str) -> str:
    normalized = normalize_model_name(model)
    if normalized.startswith("gemma"):
        return "text_only_gemma_fallback"
    if any(
        marker in normalized for marker in ("embedding", "imagen", "image", "live", "tts", "audio")
    ):
        return "non_vision_media_embedding_or_live_model"
    return "unsupported_vision_provider_or_model_family"


def visual_rag_routing_tier(
    *,
    rank: int,
    model_key: str,
    request_budget: int | None,
) -> str:
    if rank == 1:
        return "preferred_visual_rag_model"
    if model_key.startswith("gemma") and (request_budget or 0) >= 1000:
        return "high_quota_text_fallback_excluded_from_vision"
    if model_key.startswith(("ollama/", "lm_studio/", "local/")):
        return "local_fallback"
    return "fallback"


def _split_model_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


__all__ = [
    "canonical_visual_rag_model_name",
    "is_visual_rag_model_candidate",
    "vision_model_key_configured",
    "visual_rag_model",
    "visual_rag_model_chain",
    "visual_rag_model_rejection_reason",
    "visual_rag_provider_can_call_model",
    "visual_rag_routing_tier",
    "visual_rag_runtime_candidate",
]
