from __future__ import annotations

from typing import Any

from app.services.llm_quota import normalize_model_name, parse_model_budget_map


def attempt_summary_for_trace(attempts: tuple[dict[str, object], ...]) -> dict:
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
        "primary_failure_category": trace_failure_category(failed[0]) if failed else None,
    }


def model_routing_decision(
    *,
    result: Any,
    attempts: tuple[dict[str, object], ...],
    attempt_summary: dict,
    settings: Any,
) -> dict:
    rows = [attempt for attempt in attempts if isinstance(attempt, dict)]
    model_order = _configured_model_order(settings)
    model_order_keys = [normalize_model_name(model) for model in model_order]
    selected_model = str(getattr(result, "model", "") or "").strip()
    selected_key = normalize_model_name(selected_model)
    selected_rank = _model_rank(model_order_keys, selected_key)
    skipped_rows = [
        {
            "model": str(attempt.get("model") or ""),
            "model_key": normalize_model_name(str(attempt.get("model") or "")),
            "reason": str(attempt.get("outcome") or ""),
            "cooldown_seconds": attempt.get("cooldown_seconds"),
        }
        for attempt in rows
        if str(attempt.get("outcome") or "") in {"quota_daily_exhausted", "quota_cooldown"}
    ]
    daily_quota_models = _ordered_model_values(
        skipped_rows,
        reason="quota_daily_exhausted",
    )
    cooldown_models = _ordered_model_values(skipped_rows, reason="quota_cooldown")
    degraded_from_primary = bool(
        selected_rank is not None
        and selected_rank > 1
        and not bool(getattr(result, "fallback", False))
    )
    if not degraded_from_primary and attempt_summary.get("fallback_path_used"):
        degraded_from_primary = True
    selected_tier = _selected_routing_tier(settings, selected_model, selected_rank)
    return {
        "strategy": "smartest_first_then_budget_degrade",
        "selection_rule": "使用第一個尚未用完且不在冷卻中的已設定模型。",
        "configured_model_order": model_order,
        "configured_model_order_keys": model_order_keys,
        "primary_model": model_order[0] if model_order else None,
        "selected_model": selected_model or None,
        "selected_model_key": selected_key or None,
        "selected_model_rank": selected_rank,
        "selected_routing_tier": selected_tier,
        "degraded_from_primary": degraded_from_primary,
        "routing_reason": _routing_decision_reason(
            selected_rank=selected_rank,
            fallback_path_used=bool(attempt_summary.get("fallback_path_used")),
            skipped_rows=skipped_rows,
            fallback=bool(getattr(result, "fallback", False)),
        ),
        "skipped_models": skipped_rows,
        "quota_skipped_models": [row["model"] for row in skipped_rows if row["model"]],
        "daily_quota_exhausted_models": daily_quota_models,
        "cooldown_models": cooldown_models,
        "quota_skip_count": len(skipped_rows),
        "daily_quota_skip_count": len(daily_quota_models),
        "cooldown_skip_count": len(cooldown_models),
        "high_quota_fallback_used": selected_tier == "high_quota_fallback",
    }


def trace_failure_category(attempt: dict[str, object]) -> str:
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


def _ordered_attempt_values(attempts: list[dict[str, object]], key: str) -> list[str]:
    return list(
        dict.fromkeys(
            str(attempt.get(key)) for attempt in attempts if attempt.get(key) not in {None, ""}
        )
    )


def _configured_model_order(settings: Any) -> list[str]:
    primary = str(getattr(settings, "primary_llm_model", "") or "").strip()
    fallback_models = [
        model.strip()
        for model in str(getattr(settings, "llm_fallback_models", "") or "").split(",")
        if model.strip()
    ]
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    return list(dict.fromkeys(model for model in [primary, *fallback_models, local_model] if model))


def _model_rank(model_order_keys: list[str], model_key: str) -> int | None:
    if not model_key:
        return None
    try:
        return model_order_keys.index(model_key) + 1
    except ValueError:
        return None


def _selected_routing_tier(settings: Any, model: str, rank: int | None) -> str | None:
    if not model:
        return None
    model_key = normalize_model_name(model)
    if rank == 1:
        return "primary"
    request_budgets = parse_model_budget_map(
        getattr(settings, "llm_model_daily_request_budgets", "")
    )
    if model_key.startswith("gemma") and int(request_budgets.get(model_key) or 0) >= 1000:
        return "high_quota_fallback"
    if model_key.startswith(("ollama/", "lm_studio/", "local/")):
        return "local_fallback"
    return "fallback" if rank is not None else "unconfigured"


def _routing_decision_reason(
    *,
    selected_rank: int | None,
    fallback_path_used: bool,
    skipped_rows: list[dict],
    fallback: bool,
) -> str:
    if fallback:
        return "rules_engine_fallback"
    if skipped_rows:
        return "quota_or_cooldown_skip"
    if fallback_path_used or (selected_rank is not None and selected_rank > 1):
        return "selected_after_earlier_model_failed"
    if selected_rank == 1:
        return "primary_model_used"
    return "unconfigured_model_used"


def _ordered_model_values(rows: list[dict], *, reason: str) -> list[str]:
    return list(
        dict.fromkeys(
            str(row.get("model"))
            for row in rows
            if row.get("reason") == reason and str(row.get("model") or "").strip()
        )
    )


__all__ = [
    "attempt_summary_for_trace",
    "model_routing_decision",
    "trace_failure_category",
]
