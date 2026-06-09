from __future__ import annotations

import math
import re
from typing import Any

from app.services.llm_quota import normalize_model_name

_TOKEN_RE = re.compile(r"[A-Za-z0-9_+./:-]+|[\u4e00-\u9fff]|[^\s]")


def estimate_token_count(text: str) -> int:
    """Conservative local token estimate for trace/cost dashboards."""

    tokens = _TOKEN_RE.findall(str(text or ""))
    if not tokens:
        return 0
    latin_like = sum(1 for token in tokens if token.isascii() and len(token) > 1)
    cjk_or_symbol = len(tokens) - latin_like
    return max(1, int(math.ceil(latin_like * 1.25 + cjk_or_symbol)))


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
    model_rates = parse_model_cost_rate_card(getattr(settings, "llm_model_cost_rate_card_usd", ""))
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
    warning_ratio = safe_warning_ratio(getattr(settings, "llm_cost_warning_ratio", 0.8))
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


def safe_warning_ratio(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.8
    return min(1.0, max(0.01, parsed))


__all__ = [
    "estimate_token_count",
    "llm_cost_budget_status",
    "llm_cost_rates_for_model",
    "parse_model_cost_rate_card",
    "safe_warning_ratio",
]
