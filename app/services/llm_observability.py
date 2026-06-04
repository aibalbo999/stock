from __future__ import annotations

import math
import re
from typing import Any


SUPPORTED_OBSERVABILITY_PROVIDERS = ("local", "langsmith", "phoenix")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+./:-]+|[\u4e00-\u9fff]|[^\s]")


def estimate_token_count(text: str) -> int:
    """Conservative local token estimate for trace/cost dashboards."""

    tokens = _TOKEN_RE.findall(str(text or ""))
    if not tokens:
        return 0
    latin_like = sum(1 for token in tokens if token.isascii() and len(token) > 1)
    cjk_or_symbol = len(tokens) - latin_like
    return max(1, int(math.ceil(latin_like * 1.25 + cjk_or_symbol)))


def llm_observability_status(settings: Any) -> dict:
    provider = _normalized_provider(getattr(settings, "llm_observability_provider", "local"))
    enabled = bool(getattr(settings, "llm_observability_enabled", True))
    langsmith_configured = bool(getattr(settings, "langsmith_api_key", None))
    phoenix_endpoint = str(getattr(settings, "phoenix_endpoint", "") or "").strip()
    external_configured = (
        (provider == "langsmith" and langsmith_configured)
        or (provider == "phoenix" and bool(phoenix_endpoint))
    )
    input_rate = max(0.0, float(getattr(settings, "llm_input_cost_per_1k_tokens_usd", 0.0) or 0.0))
    output_rate = max(0.0, float(getattr(settings, "llm_output_cost_per_1k_tokens_usd", 0.0) or 0.0))
    return {
        "enabled": enabled,
        "provider": provider,
        "supported_providers": list(SUPPORTED_OBSERVABILITY_PROVIDERS),
        "local_trace_enabled": enabled,
        "external_trace_configured": external_configured,
        "langsmith_configured": langsmith_configured,
        "phoenix_endpoint_configured": bool(phoenix_endpoint),
        "captured_fields": [
            "provider",
            "model",
            "latency_ms",
            "attempt_count",
            "input_token_estimate",
            "output_token_estimate",
            "total_token_estimate",
            "estimated_cost_usd",
            "retrieval_latency_ms",
            "reranker_status",
        ],
        "cost_tracking_enabled": enabled,
        "cost_rate_card_configured": bool(input_rate or output_rate),
        "input_cost_per_1k_tokens_usd_configured": bool(input_rate),
        "output_cost_per_1k_tokens_usd_configured": bool(output_rate),
    }


def build_llm_observability_trace(
    *,
    prompt: str,
    result: Any,
    latency_ms: float,
    operation: str,
    settings: Any,
) -> dict:
    status = llm_observability_status(settings)
    input_tokens = estimate_token_count(prompt)
    output_tokens = estimate_token_count(str(getattr(result, "text", "") or ""))
    input_rate = max(0.0, float(getattr(settings, "llm_input_cost_per_1k_tokens_usd", 0.0) or 0.0))
    output_rate = max(0.0, float(getattr(settings, "llm_output_cost_per_1k_tokens_usd", 0.0) or 0.0))
    estimated_cost = None
    if input_rate or output_rate:
        estimated_cost = round((input_tokens / 1000 * input_rate) + (output_tokens / 1000 * output_rate), 8)
    attempts = tuple(getattr(result, "attempts", ()) or ())
    return {
        "enabled": status["enabled"],
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None),
        "operation": operation,
        "latency_ms": round(max(0.0, float(latency_ms)), 3),
        "attempt_count": len(attempts),
        "fallback": bool(getattr(result, "fallback", False)),
        "input_token_estimate": input_tokens,
        "output_token_estimate": output_tokens,
        "total_token_estimate": input_tokens + output_tokens,
        "estimated_cost_usd": estimated_cost,
        "cost_tracking_mode": "configured_rate_card" if estimated_cost is not None else "token_estimate_only",
        "external_trace_provider": status["provider"] if status["external_trace_configured"] else None,
        "external_trace_configured": status["external_trace_configured"],
    }


def _normalized_provider(provider: object) -> str:
    value = str(provider or "local").strip().lower().replace("-", "_")
    return value if value in SUPPORTED_OBSERVABILITY_PROVIDERS else "local"
