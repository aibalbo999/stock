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
            "models_tried",
            "fallback_path_used",
            "primary_failure_category",
            "input_token_estimate",
            "output_token_estimate",
            "total_token_estimate",
            "estimated_cost_usd",
            "cost_tracking_mode",
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
    attempt_summary = _attempt_summary_for_trace(attempts)
    return {
        "enabled": status["enabled"],
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None),
        "operation": operation,
        "latency_ms": round(max(0.0, float(latency_ms)), 3),
        "attempt_count": len(attempts),
        "models_tried": attempt_summary.get("models_tried") or [],
        "providers_tried": attempt_summary.get("providers_tried") or [],
        "fallback_path_used": attempt_summary.get("fallback_path_used"),
        "primary_failure_category": attempt_summary.get("primary_failure_category"),
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


def _attempt_summary_for_trace(attempts: tuple[dict[str, object], ...]) -> dict:
    rows = [attempt for attempt in attempts if isinstance(attempt, dict)]
    first = rows[0] if rows else {}
    final = rows[-1] if rows else {}
    failed = [attempt for attempt in rows if str(attempt.get("outcome") or "") != "success"]
    return {
        "models_tried": _ordered_attempt_values(rows, "model"),
        "providers_tried": _ordered_attempt_values(rows, "provider"),
        "fallback_path_used": bool(
            rows
            and final.get("outcome") == "success"
            and (
                str(first.get("model") or "") != str(final.get("model") or "")
                or str(first.get("provider") or "") != str(final.get("provider") or "")
            )
        ),
        "primary_failure_category": _trace_failure_category(failed[0]) if failed else None,
    }


def _ordered_attempt_values(attempts: list[dict[str, object]], key: str) -> list[str]:
    return list(
        dict.fromkeys(
            str(attempt.get(key))
            for attempt in attempts
            if attempt.get(key) not in {None, ""}
        )
    )


def _trace_failure_category(attempt: dict[str, object]) -> str:
    status = attempt.get("status")
    if status is not None:
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            return "http_error"
        if status_code == 429:
            return "rate_limited"
        if status_code in {401, 403}:
            return "auth_or_permission_error"
        if status_code in {500, 502, 503, 504}:
            return "upstream_error"
        return "http_error"
    return str(attempt.get("outcome") or "unknown_error")
