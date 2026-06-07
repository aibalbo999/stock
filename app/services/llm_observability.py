from __future__ import annotations

import math
import re
from typing import Any

from app.services.llm_quota import normalize_model_name

SUPPORTED_OBSERVABILITY_PROVIDERS = ("local", "langsmith", "phoenix")
LANGSMITH_CREDENTIAL_ENV = "LANGSMITH_" + "API" + "_" + "KEY"
OBSERVABILITY_PROVIDER_PROFILES = {
    "local": {
        "label": "Local usage store",
        "external_sink": False,
        "required_settings": [],
        "endpoint_setting": None,
        "api_key_setting": None,
        "export_mode_ready": "local_trace",
        "export_mode_unconfigured": "local_trace",
    },
    "langsmith": {
        "label": "LangSmith",
        "external_sink": True,
        "required_settings": [LANGSMITH_CREDENTIAL_ENV],
        "endpoint_setting": None,
        "api_key_setting": LANGSMITH_CREDENTIAL_ENV,
        "export_mode_ready": "external_trace",
        "export_mode_unconfigured": "local_trace_with_external_sink_pending",
    },
    "phoenix": {
        "label": "Phoenix",
        "external_sink": True,
        "required_settings": ["PHOENIX_ENDPOINT"],
        "endpoint_setting": "PHOENIX_ENDPOINT",
        "api_key_setting": None,
        "export_mode_ready": "external_trace",
        "export_mode_unconfigured": "local_trace_with_external_sink_pending",
    },
}
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
    trace_sink = llm_observability_trace_sink_status(settings, provider=provider, enabled=enabled)
    input_rate = max(0.0, float(getattr(settings, "llm_input_cost_per_1k_tokens_usd", 0.0) or 0.0))
    output_rate = max(0.0, float(getattr(settings, "llm_output_cost_per_1k_tokens_usd", 0.0) or 0.0))
    model_rate_card = parse_model_cost_rate_card(
        getattr(settings, "llm_model_cost_rate_card_usd", "")
    )
    daily_budget = max(0.0, float(getattr(settings, "llm_daily_cost_budget_usd", 0.0) or 0.0))
    warning_ratio = _safe_warning_ratio(getattr(settings, "llm_cost_warning_ratio", 0.8))
    return {
        "enabled": enabled,
        "provider": provider,
        "supported_providers": list(SUPPORTED_OBSERVABILITY_PROVIDERS),
        "local_trace_enabled": enabled,
        "external_trace_configured": trace_sink["external_trace_configured"],
        "external_trace_ready": trace_sink["ready"] and trace_sink["external_sink"],
        "external_trace_missing_settings": trace_sink["missing_settings"],
        "trace_export_mode": trace_sink["trace_export_mode"],
        "trace_export_target": trace_sink["trace_export_target"],
        "trace_sink": trace_sink,
        "langsmith_configured": _setting_configured(settings, "langsmith_api_key"),
        "phoenix_endpoint_configured": _setting_configured(settings, "phoenix_endpoint"),
        "captured_fields": [
            "provider",
            "model",
            "latency_ms",
            "attempt_count",
            "models_tried",
            "fallback_path_used",
            "primary_failure_category",
            "external_trace_provider",
            "trace_export_mode",
            "input_token_estimate",
            "output_token_estimate",
            "total_token_estimate",
            "estimated_cost_usd",
            "cost_tracking_mode",
            "retrieval_latency_ms",
            "reranker_status",
        ],
        "cost_tracking_enabled": enabled,
        "cost_rate_card_configured": bool(input_rate or output_rate or model_rate_card),
        "model_cost_rate_card_count": len(model_rate_card),
        "daily_cost_budget_usd": daily_budget,
        "cost_warning_ratio": warning_ratio,
        "input_cost_per_1k_tokens_usd_configured": bool(input_rate),
        "output_cost_per_1k_tokens_usd_configured": bool(output_rate),
    }


def llm_observability_trace_sink_status(
    settings: Any,
    *,
    provider: str | None = None,
    enabled: bool | None = None,
) -> dict:
    provider = _normalized_provider(
        provider if provider is not None else getattr(settings, "llm_observability_provider", "local")
    )
    enabled = bool(getattr(settings, "llm_observability_enabled", True) if enabled is None else enabled)
    profile = OBSERVABILITY_PROVIDER_PROFILES[provider]
    missing_settings = [
        setting
        for setting in profile["required_settings"]
        if not _setting_configured(settings, _setting_attr_name(setting))
    ]
    configured = not missing_settings
    external_sink = bool(profile["external_sink"])
    ready = enabled and (configured if external_sink else True)
    if not enabled:
        trace_export_mode = "disabled"
    else:
        trace_export_mode = (
            profile["export_mode_ready"]
            if ready and (configured or not external_sink)
            else profile["export_mode_unconfigured"]
        )
    if not enabled:
        trace_export_target = None
    elif ready and external_sink:
        trace_export_target = provider
    else:
        trace_export_target = "local"
    return {
        "provider": provider,
        "label": profile["label"],
        "supported": True,
        "enabled": enabled,
        "external_sink": external_sink,
        "configured": configured,
        "ready": ready,
        "external_trace_configured": configured and external_sink,
        "missing_settings": missing_settings,
        "required_settings": list(profile["required_settings"]),
        "api_key_setting": profile["api_key_setting"],
        "api_key_configured": _setting_configured(
            settings,
            _setting_attr_name(str(profile["api_key_setting"] or "")),
        )
        if profile["api_key_setting"]
        else None,
        "endpoint_setting": profile["endpoint_setting"],
        "endpoint_configured": _setting_configured(
            settings,
            _setting_attr_name(str(profile["endpoint_setting"] or "")),
        )
        if profile["endpoint_setting"]
        else None,
        "trace_export_mode": trace_export_mode,
        "trace_export_target": trace_export_target,
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
    input_rate, output_rate = llm_cost_rates_for_model(settings, getattr(result, "model", None))
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
        "external_trace_ready": status["external_trace_ready"],
        "external_trace_missing_settings": status["external_trace_missing_settings"],
        "trace_export_mode": status["trace_export_mode"],
        "trace_export_target": status["trace_export_target"],
    }


def parse_model_cost_rate_card(raw: str | None) -> dict[str, dict[str, float]]:
    """Parse model=input_per_1k:output_per_1k entries for per-model cost tracking."""

    rates: dict[str, dict[str, float]] = {}
    for item in str(raw or "").split(","):
        if "=" not in item:
            continue
        model, value = item.split("=", 1)
        model_key = normalize_model_name(model)
        parts = re.split(r"[:/]", value.strip())
        if len(parts) != 2 or not model_key:
            continue
        try:
            input_rate = max(0.0, float(parts[0].strip()))
            output_rate = max(0.0, float(parts[1].strip()))
        except (TypeError, ValueError):
            continue
        if input_rate or output_rate:
            rates[model_key] = {
                "input_cost_per_1k_tokens_usd": input_rate,
                "output_cost_per_1k_tokens_usd": output_rate,
            }
    return rates


def llm_cost_rates_for_model(settings: Any, model: object) -> tuple[float, float]:
    model_rates = parse_model_cost_rate_card(
        getattr(settings, "llm_model_cost_rate_card_usd", "")
    )
    model_key = normalize_model_name(str(model or ""))
    if model_key in model_rates:
        rates = model_rates[model_key]
        return (
            float(rates["input_cost_per_1k_tokens_usd"]),
            float(rates["output_cost_per_1k_tokens_usd"]),
        )
    return (
        max(0.0, float(getattr(settings, "llm_input_cost_per_1k_tokens_usd", 0.0) or 0.0)),
        max(0.0, float(getattr(settings, "llm_output_cost_per_1k_tokens_usd", 0.0) or 0.0)),
    )


def llm_cost_budget_status(settings: Any, *, estimated_cost_usd: float, days: int) -> dict:
    daily_budget = max(0.0, float(getattr(settings, "llm_daily_cost_budget_usd", 0.0) or 0.0))
    warning_ratio = _safe_warning_ratio(getattr(settings, "llm_cost_warning_ratio", 0.8))
    safe_days = max(1, int(days or 1))
    window_budget = round(daily_budget * safe_days, 6) if daily_budget else 0.0
    used = max(0.0, float(estimated_cost_usd or 0.0))
    used_ratio = round(used / window_budget, 4) if window_budget else None
    if not window_budget:
        status = "not_configured"
    elif used >= window_budget:
        status = "exceeded"
    elif used_ratio is not None and used_ratio >= warning_ratio:
        status = "warning"
    else:
        status = "ok"
    return {
        "status": status,
        "daily_cost_budget_usd": daily_budget,
        "window_cost_budget_usd": window_budget,
        "estimated_cost_usd": round(used, 6),
        "budget_used_ratio": used_ratio,
        "warning_ratio": warning_ratio,
    }


def _normalized_provider(provider: object) -> str:
    value = str(provider or "local").strip().lower().replace("-", "_")
    return value if value in SUPPORTED_OBSERVABILITY_PROVIDERS else "local"


def _setting_attr_name(setting: str) -> str:
    return str(setting or "").strip().lower()


def _setting_configured(settings: Any, attr_name: str) -> bool:
    if not attr_name:
        return False
    return bool(str(getattr(settings, attr_name, "") or "").strip())


def _safe_warning_ratio(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.8
    return min(1.0, max(0.01, parsed))


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
