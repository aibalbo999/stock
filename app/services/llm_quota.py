from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.db.session import session_scope
from app.services.persistence import LLMUsageRepository

NON_REQUEST_ATTEMPT_OUTCOMES = {
    "dependency_unavailable",
    "missing_api_key",
    "missing_model",
    "quota_cooldown",
    "quota_daily_exhausted",
    "timeout",
}
DEFAULT_QUOTA_WARNING_RATIO = 0.8
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


class LLMQuotaGovernanceService:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any] = get_settings,
        session_scope_factory: Callable = session_scope,
        llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
        clock: Callable[[], datetime] = utc_now_naive,
    ) -> None:
        self.settings_provider = settings_provider
        self.session_scope_factory = session_scope_factory
        self.llm_usage_repository_cls = llm_usage_repository_cls
        self.clock = clock

    def summary(self) -> dict:
        settings = self.settings_provider()
        window = self._quota_window(settings)
        request_budgets = parse_model_budget_map(getattr(settings, "llm_model_daily_request_budgets", ""))
        token_budgets = parse_model_budget_map(getattr(settings, "llm_model_daily_token_budgets", ""))
        warning_ratio = _safe_warning_ratio(
            getattr(settings, "llm_quota_warning_ratio", DEFAULT_QUOTA_WARNING_RATIO)
        )
        default_cooldown_seconds = max(
            0.0,
            float(getattr(settings, "llm_model_quota_cooldown_seconds", 0.0) or 0.0),
        )
        model_order = self._model_order(settings)
        usage_records = self._usage_records(window["start_utc_naive"])
        usage_by_model = self._usage_by_model(usage_records)
        quota_health_by_model = self._quota_health_by_model(
            usage_records,
            now_utc_naive=window["now_utc_naive"],
            default_cooldown_seconds=default_cooldown_seconds,
        )
        configured_by_key = {normalize_model_name(model): model for model in model_order}
        for model_key in sorted(
            (set(usage_by_model) | set(quota_health_by_model)) - set(configured_by_key)
        ):
            configured_by_key[model_key] = (
                usage_by_model.get(model_key, {}).get("model")
                or quota_health_by_model.get(model_key, {}).get("model")
                or model_key
            )
        rows = []
        for model_key, display_model in configured_by_key.items():
            usage = usage_by_model.get(model_key, {})
            quota_health = quota_health_by_model.get(model_key, {})
            request_budget = request_budgets.get(model_key)
            token_budget = token_budgets.get(model_key)
            requests_used = int(usage.get("request_count") or 0)
            tokens_used = int(usage.get("total_token_estimate") or 0)
            active_cooldown_seconds = int(quota_health.get("active_cooldown_seconds") or 0)
            request_remaining = _remaining(request_budget, requests_used)
            token_remaining = _remaining(token_budget, tokens_used)
            request_used_ratio = _used_ratio(request_budget, requests_used)
            token_used_ratio = _used_ratio(token_budget, tokens_used)
            usage_ratio = _max_ratio(request_used_ratio, token_used_ratio)
            request_exhausted = request_budget is not None and request_remaining is not None and request_remaining <= 0
            token_exhausted = token_budget is not None and token_remaining is not None and token_remaining <= 0
            has_budget = request_budget is not None or token_budget is not None
            status = (
                "exhausted"
                if request_exhausted or token_exhausted
                else "cooldown"
                if active_cooldown_seconds > 0
                else "available"
                if has_budget
                else "tracking_only"
            )
            request_warning = (
                status != "exhausted"
                and request_used_ratio is not None
                and request_used_ratio >= warning_ratio
            )
            token_warning = (
                status != "exhausted"
                and token_used_ratio is not None
                and token_used_ratio >= warning_ratio
            )
            quota_warning = request_warning or token_warning
            risk_level = _risk_level(
                status=status,
                has_budget=has_budget,
                quota_warning=quota_warning,
            )
            routing_tier = _routing_tier(model_order, display_model, request_budget)
            rows.append(
                {
                    "model": display_model,
                    "model_key": model_key,
                    "configured": model_key in {normalize_model_name(model) for model in model_order},
                    "rank": _rank_for_model(model_order, display_model),
                    "completion_count": int(usage.get("completion_count") or 0),
                    "requests_used": requests_used,
                    "request_budget": request_budget,
                    "free_tier_request_budget_reference": (
                        FREE_TIER_REQUEST_BUDGET_REFERENCES.get(model_key)
                    ),
                    "free_tier_token_budget_reference": (
                        FREE_TIER_TOKEN_BUDGET_REFERENCES.get(model_key)
                    ),
                    "quota_reference_source": _quota_reference_source(model_key),
                    "quota_reference_note": _quota_reference_note(model_key),
                    "requests_remaining": request_remaining,
                    "request_used_ratio": request_used_ratio,
                    "tokens_used": tokens_used,
                    "token_budget": token_budget,
                    "tokens_remaining": token_remaining,
                    "token_used_ratio": token_used_ratio,
                    "usage_ratio": usage_ratio,
                    "estimated_cost_usd": round(float(usage.get("estimated_cost_usd") or 0.0), 6),
                    "fallback_count": int(usage.get("fallback_count") or 0),
                    "retryable_failure_count": int(usage.get("retryable_failure_count") or 0),
                    "quota_hit_count": int(quota_health.get("quota_hit_count") or 0),
                    "quota_skip_count": int(quota_health.get("quota_skip_count") or 0),
                    "daily_quota_skip_count": int(
                        quota_health.get("daily_quota_skip_count") or 0
                    ),
                    "cooldown_skip_count": int(quota_health.get("cooldown_skip_count") or 0),
                    "active_cooldown_seconds": active_cooldown_seconds,
                    "last_quota_hit_at": quota_health.get("last_quota_hit_at"),
                    "status": status,
                    "status_reason": _status_reason(
                        status=status,
                        request_exhausted=request_exhausted,
                        token_exhausted=token_exhausted,
                        request_warning=request_warning,
                        token_warning=token_warning,
                        has_budget=has_budget,
                        active_cooldown_seconds=active_cooldown_seconds,
                    ),
                    "quota_warning": quota_warning,
                    "risk_level": risk_level,
                    "routing_tier": routing_tier,
                    "routing_reason": _routing_reason(
                        status=status,
                        quota_warning=quota_warning,
                        model_order=model_order,
                        model=display_model,
                        request_budget=request_budget,
                        active_cooldown_seconds=active_cooldown_seconds,
                    ),
                    "next_action": _next_action(
                        status=status,
                        risk_level=risk_level,
                        routing_tier=routing_tier,
                        active_cooldown_seconds=active_cooldown_seconds,
                    ),
                }
            )
        rows.sort(key=lambda item: (item["rank"] if item["rank"] is not None else 999, item["model"]))
        recommended = next(
            (
                item
                for item in rows
                if item["configured"] and item["status"] not in {"exhausted", "cooldown"}
            ),
            None,
        )
        exhausted_before_recommendation = [
            item["model"]
            for item in rows
            if recommended and item.get("configured") and int(item.get("rank") or 999) < int(recommended.get("rank") or 999)
        ]
        totals = {
            "request_count": sum(int(item.get("requests_used") or 0) for item in rows),
            "completion_count": sum(int(item.get("completion_count") or 0) for item in rows),
            "total_token_estimate": sum(int(item.get("tokens_used") or 0) for item in rows),
            "estimated_cost_usd": round(sum(float(item.get("estimated_cost_usd") or 0.0) for item in rows), 6),
        }
        return {
            "window": {
                "timezone": window["timezone"],
                "now": window["now_local"].isoformat(),
                "start": window["start_local"].isoformat(),
                "end": window["end_local"].isoformat(),
                "reset_in_seconds": window["reset_in_seconds"],
            },
            "model_order": model_order,
            "recommended_model": recommended["model"] if recommended else None,
            "recommended_model_key": recommended["model_key"] if recommended else None,
            "recommended_rank": recommended["rank"] if recommended else None,
            "recommended_routing_tier": (
                recommended["routing_tier"] if recommended else None
            ),
            "recommended_status": recommended["status"] if recommended else None,
            "recommended_reason": _recommended_reason(
                recommended,
                exhausted_before_recommendation,
                warning_ratio,
            ),
            "models": rows,
            "quota_warning_ratio": warning_ratio,
            "alerts": _quota_alerts(rows),
            "totals": totals,
            "routing_policy": {
                "strategy": "smartest_first_then_budget_degrade",
                "selection_rule": "Use the first configured model that is not exhausted in the current quota window.",
                "warning_rule": (
                    "Warning thresholds only surface risk; routing still uses smarter models "
                    "until their configured budget is exhausted."
                ),
                "exhausted_before_recommendation": exhausted_before_recommendation,
                "high_quota_fallback_models": [
                    item["model"] for item in rows if item.get("routing_tier") == "high_quota_fallback"
                ],
                "quota_hit_models": [
                    item["model"] for item in rows if int(item.get("quota_hit_count") or 0)
                ],
                "cooldown_models": [
                    item["model"] for item in rows if int(item.get("active_cooldown_seconds") or 0)
                ],
            },
            "budget_source": {
                "request_budgets_configured": bool(request_budgets),
                "token_budgets_configured": bool(token_budgets),
                "settings": {
                    "llm_model_daily_request_budgets": getattr(settings, "llm_model_daily_request_budgets", ""),
                    "llm_model_daily_token_budgets": getattr(settings, "llm_model_daily_token_budgets", ""),
                },
                "free_tier_reference": {
                    **FREE_TIER_RATE_LIMIT_SOURCE,
                    "request_budgets": FREE_TIER_REQUEST_BUDGET_REFERENCES,
                    "token_budgets": FREE_TIER_TOKEN_BUDGET_REFERENCES,
                    "project_configured_model_notes": PROJECT_CONFIGURED_MODEL_BUDGET_NOTES,
                },
                "note": (
                    "Gemini API free-tier limits are project-level and can vary by model/version; "
                    "request counts are attributed from persisted attempts/models_tried when available, "
                    "and settings should match the limits shown in Google AI Studio. "
                    "Quota warnings do not change routing; only exhausted models are skipped."
                ),
            },
        }

    def exhausted_model_keys(self) -> set[str]:
        return {
            str(item.get("model_key") or "")
            for item in self.summary().get("models", [])
            if item.get("status") in {"exhausted", "cooldown"} and item.get("model_key")
        }

    def active_cooldown_seconds(self, model: str) -> float:
        model_key = normalize_model_name(model)
        if not model_key:
            return 0.0
        for item in self.summary().get("models", []):
            if normalize_model_name(str(item.get("model_key") or item.get("model") or "")) == model_key:
                return max(0.0, float(item.get("active_cooldown_seconds") or 0.0))
        return 0.0

    def _usage_records(self, since_utc_naive: datetime) -> list[dict]:
        with self.session_scope_factory() as session:
            repository = self.llm_usage_repository_cls(session)
            records = repository.since(since_utc_naive)
            return [repository.to_dict(record) for record in records]

    @staticmethod
    def _usage_by_model(records: list[dict]) -> dict[str, dict]:
        usage: dict[str, dict] = {}
        for record in records:
            model = str(record.get("model") or "unknown")
            model_key = normalize_model_name(model)
            request_counts = _model_request_counts(record)
            if not request_counts:
                request_counts = {model_key: 1}
            retryable_failures = _retryable_failures_by_model(record)
            for attempted_model_key, request_count in request_counts.items():
                bucket = _usage_bucket(usage, attempted_model_key, _display_model_for_key(attempted_model_key, record))
                bucket["request_count"] += int(request_count)
                bucket["retryable_failure_count"] += int(retryable_failures.get(attempted_model_key, 0))

            final_bucket = _usage_bucket(usage, model_key, model)
            final_bucket["completion_count"] += 1
            final_bucket["total_token_estimate"] += int(record.get("total_token_estimate") or 0)
            final_bucket["estimated_cost_usd"] += float(record.get("estimated_cost_usd") or 0.0)
            final_bucket["fallback_count"] += 1 if record.get("fallback") else 0
            if not retryable_failures:
                final_bucket["retryable_failure_count"] += int(record.get("retryable_failure_count") or 0)
        return usage

    @staticmethod
    def _quota_health_by_model(
        records: list[dict],
        *,
        now_utc_naive: datetime,
        default_cooldown_seconds: float,
    ) -> dict[str, dict]:
        health: dict[str, dict] = {}
        for record in records:
            record_created_at = _parse_record_datetime(record.get("created_at"))
            attempts = record.get("attempts")
            if not isinstance(attempts, list):
                continue
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                model_key = normalize_model_name(str(attempt.get("model") or ""))
                if not model_key:
                    continue
                bucket = health.setdefault(
                    model_key,
                    {
                        "model": _display_model_for_key(model_key, record),
                        "quota_hit_count": 0,
                        "daily_quota_skip_count": 0,
                        "cooldown_skip_count": 0,
                        "quota_skip_count": 0,
                        "active_cooldown_seconds": 0,
                        "last_quota_hit_at": None,
                    },
                )
                outcome = str(attempt.get("outcome") or "")
                status = _safe_int(attempt.get("status"))
                if status == 429:
                    bucket["quota_hit_count"] += 1
                    _record_last_quota_hit(bucket, record_created_at)
                    cooldown = _attempt_cooldown_seconds(
                        attempt,
                        default_seconds=default_cooldown_seconds,
                    )
                    bucket["active_cooldown_seconds"] = max(
                        int(bucket.get("active_cooldown_seconds") or 0),
                        _cooldown_remaining_seconds(
                            record_created_at,
                            now_utc_naive=now_utc_naive,
                            cooldown_seconds=cooldown,
                        ),
                    )
                if outcome == "quota_daily_exhausted":
                    bucket["daily_quota_skip_count"] += 1
                    bucket["quota_skip_count"] += 1
                elif outcome == "quota_cooldown":
                    bucket["cooldown_skip_count"] += 1
                    bucket["quota_skip_count"] += 1
                    cooldown = _attempt_cooldown_seconds(
                        attempt,
                        default_seconds=default_cooldown_seconds,
                    )
                    bucket["active_cooldown_seconds"] = max(
                        int(bucket.get("active_cooldown_seconds") or 0),
                        _cooldown_remaining_seconds(
                            record_created_at,
                            now_utc_naive=now_utc_naive,
                            cooldown_seconds=cooldown,
                        ),
                    )
        return health

    @staticmethod
    def _model_order(settings: Any) -> list[str]:
        models = [str(getattr(settings, "primary_llm_model", "") or "").strip()]
        models.extend(
            model.strip()
            for model in str(getattr(settings, "llm_fallback_models", "") or "").split(",")
            if model.strip()
        )
        local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
        if local_model:
            models.append(local_model)
        return list(dict.fromkeys(model for model in models if model))

    def _quota_window(self, settings: Any) -> dict:
        timezone_name = str(getattr(settings, "llm_quota_window_timezone", "") or "America/Los_Angeles")
        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone_name = "UTC"
            tz = timezone.utc
        now_utc = self.clock()
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)
        start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
        end_local = datetime.combine(now_local.date(), time.max, tzinfo=tz)
        return {
            "timezone": timezone_name,
            "now_local": now_local,
            "now_utc_naive": now_utc.replace(tzinfo=None),
            "start_local": start_local,
            "end_local": end_local,
            "reset_in_seconds": max(0, int((end_local - now_local).total_seconds())),
            "start_utc_naive": start_local.astimezone(timezone.utc).replace(tzinfo=None),
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


def normalize_model_name(model: str) -> str:
    normalized = str(model or "").strip().lower()
    for prefix in ("models/", "gemini/", "google/"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
    return normalized


def _usage_bucket(usage: dict[str, dict], model_key: str, display_model: str) -> dict:
    return usage.setdefault(
        model_key,
        {
            "model": display_model or model_key,
            "completion_count": 0,
            "request_count": 0,
            "total_token_estimate": 0,
            "estimated_cost_usd": 0.0,
            "fallback_count": 0,
            "retryable_failure_count": 0,
        },
    )


def _model_request_counts(record: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    attempts = record.get("attempts")
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            outcome = str(attempt.get("outcome") or "")
            if outcome in NON_REQUEST_ATTEMPT_OUTCOMES:
                continue
            model_key = normalize_model_name(str(attempt.get("model") or ""))
            if model_key:
                counts[model_key] = counts.get(model_key, 0) + 1
    if counts:
        return counts

    models_tried = record.get("models_tried")
    if isinstance(models_tried, list):
        for model in models_tried:
            model_key = normalize_model_name(str(model or ""))
            if model_key and model_key not in counts:
                counts[model_key] = 1
    return counts


def _retryable_failures_by_model(record: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    attempts = record.get("attempts")
    if not isinstance(attempts, list):
        return counts
    for attempt in attempts:
        if not isinstance(attempt, dict) or attempt.get("retryable") is not True:
            continue
        outcome = str(attempt.get("outcome") or "")
        if outcome in {"quota_cooldown", "quota_daily_exhausted"}:
            continue
        model_key = normalize_model_name(str(attempt.get("model") or ""))
        if model_key:
            counts[model_key] = counts.get(model_key, 0) + 1
    return counts


def _display_model_for_key(model_key: str, record: dict) -> str:
    for value in _record_model_values(record):
        if normalize_model_name(value) == model_key:
            return value
    return model_key


def _record_model_values(record: dict) -> list[str]:
    values: list[str] = []
    model = str(record.get("model") or "").strip()
    if model:
        values.append(model)
    models_tried = record.get("models_tried")
    if isinstance(models_tried, list):
        values.extend(str(item or "").strip() for item in models_tried if str(item or "").strip())
    attempts = record.get("attempts")
    if isinstance(attempts, list):
        values.extend(
            str(attempt.get("model") or "").strip()
            for attempt in attempts
            if isinstance(attempt, dict) and str(attempt.get("model") or "").strip()
        )
    return list(dict.fromkeys(values))


def _remaining(budget: int | None, used: int) -> int | None:
    if budget is None:
        return None
    return max(0, int(budget) - int(used))


def _used_ratio(budget: int | None, used: int) -> float | None:
    if budget is None or int(budget) <= 0:
        return None
    return round(max(0.0, float(used) / float(budget)), 4)


def _max_ratio(*values: float | None) -> float | None:
    available = [value for value in values if value is not None]
    if not available:
        return None
    return max(available)


def _rank_for_model(model_order: list[str], model: str) -> int | None:
    model_key = normalize_model_name(model)
    for index, candidate in enumerate(model_order, start=1):
        if normalize_model_name(candidate) == model_key:
            return index
    return None


def _status_reason(
    *,
    status: str,
    request_exhausted: bool,
    token_exhausted: bool,
    request_warning: bool,
    token_warning: bool,
    has_budget: bool,
    active_cooldown_seconds: int,
) -> str:
    if status == "exhausted" and request_exhausted:
        return "request_budget_exhausted"
    if status == "exhausted" and token_exhausted:
        return "token_budget_exhausted"
    if status == "cooldown" and active_cooldown_seconds > 0:
        return "quota_cooldown_active"
    if request_warning:
        return "request_budget_near_limit"
    if token_warning:
        return "token_budget_near_limit"
    if has_budget:
        return "within_configured_budget"
    return "no_budget_configured_tracking_only"


def _risk_level(*, status: str, has_budget: bool, quota_warning: bool) -> str:
    if status == "exhausted":
        return "exhausted"
    if status == "cooldown":
        return "cooldown"
    if quota_warning:
        return "warning"
    if has_budget:
        return "normal"
    return "tracking_only"


def _routing_tier(model_order: list[str], model: str, request_budget: int | None) -> str:
    rank = _rank_for_model(model_order, model)
    model_key = normalize_model_name(model)
    if rank == 1:
        return "primary"
    if model_key.startswith("gemma") and (request_budget or 0) >= 1000:
        return "high_quota_fallback"
    if model_key.startswith(("ollama/", "lm_studio/", "local/")):
        return "local_fallback"
    return "fallback"


def _routing_reason(
    *,
    status: str,
    quota_warning: bool,
    model_order: list[str],
    model: str,
    request_budget: int | None,
    active_cooldown_seconds: int,
) -> str:
    tier = _routing_tier(model_order, model, request_budget)
    if status == "exhausted":
        return "Skipped until the next quota window because the configured daily budget is exhausted."
    if status == "cooldown":
        return (
            "Temporarily skipped because a recent quota/rate-limit hit is still cooling down "
            f"for about {active_cooldown_seconds} seconds."
        )
    if quota_warning:
        return "Still eligible until exhausted; watch remaining quota before starting large batches."
    if tier == "primary":
        return "First choice while quota remains."
    if tier == "high_quota_fallback":
        return "High-quota fallback for long or lower-priority text tasks after smarter models are exhausted."
    if tier == "local_fallback":
        return "Local gateway fallback when provider-backed models cannot be used."
    return "Fallback candidate used only after earlier ranked models are exhausted or unavailable."


def _next_action(
    *,
    status: str,
    risk_level: str,
    routing_tier: str,
    active_cooldown_seconds: int,
) -> str:
    if status == "exhausted":
        return "No action needed for routing; this model is skipped until the quota window resets."
    if status == "cooldown":
        return (
            "No manual action needed; this model is skipped until cooldown expires "
            f"in about {active_cooldown_seconds} seconds."
        )
    if risk_level == "warning":
        return "Keep using this model until exhausted; defer large batch runs if you need to preserve its remaining quota."
    if routing_tier == "high_quota_fallback":
        return "Keep as the high-volume fallback after smarter models are exhausted."
    if risk_level == "tracking_only":
        return "Configure a daily budget if this model should participate in hard routing."
    return "No immediate action."


def _recommended_reason(
    recommended: dict | None,
    exhausted_before_recommendation: list[str],
    warning_ratio: float,
) -> str:
    if not recommended:
        return "No configured model has remaining tracked quota in the current window."
    if not exhausted_before_recommendation and recommended.get("quota_warning"):
        percent = int(round(warning_ratio * 100))
        return (
            "Top-ranked configured model still has remaining tracked quota; "
            f"it has reached the {percent}% warning threshold."
        )
    if not exhausted_before_recommendation:
        return "Top-ranked configured model still has remaining tracked quota."
    skipped = ", ".join(exhausted_before_recommendation)
    return f"Earlier model(s) exhausted in the current window: {skipped}."


def _quota_alerts(rows: list[dict]) -> list[dict]:
    alerts = []
    for row in rows:
        if not row.get("configured"):
            continue
        risk_level = str(row.get("risk_level") or "")
        if risk_level not in {"warning", "exhausted", "cooldown"}:
            continue
        code = (
            "llm_quota_exhausted"
            if risk_level == "exhausted"
            else "llm_quota_cooldown"
            if risk_level == "cooldown"
            else "llm_quota_near_limit"
        )
        severity = "critical" if risk_level == "exhausted" else "warning"
        alerts.append(
            {
                "code": code,
                "severity": severity,
                "model": row.get("model"),
                "model_key": row.get("model_key"),
                "risk_level": risk_level,
                "status": row.get("status"),
                "status_reason": row.get("status_reason"),
                "usage_ratio": row.get("usage_ratio"),
                "requests_used": row.get("requests_used"),
                "request_budget": row.get("request_budget"),
                "requests_remaining": row.get("requests_remaining"),
                "tokens_used": row.get("tokens_used"),
                "token_budget": row.get("token_budget"),
                "tokens_remaining": row.get("tokens_remaining"),
                "quota_hit_count": row.get("quota_hit_count"),
                "quota_skip_count": row.get("quota_skip_count"),
                "active_cooldown_seconds": row.get("active_cooldown_seconds"),
                "last_quota_hit_at": row.get("last_quota_hit_at"),
                "next_action": row.get("next_action"),
                "message": _quota_alert_message(row),
            }
        )
    return alerts


def _quota_alert_message(row: dict) -> str:
    model = str(row.get("model") or "model")
    status_reason = str(row.get("status_reason") or "")
    if row.get("risk_level") == "exhausted":
        return f"{model} is exhausted for the current configured quota window."
    if row.get("risk_level") == "cooldown":
        seconds = int(row.get("active_cooldown_seconds") or 0)
        return f"{model} is cooling down after recent quota/rate-limit hits for about {seconds} seconds."
    if status_reason == "request_budget_near_limit":
        return f"{model} is near its configured daily request budget."
    if status_reason == "token_budget_near_limit":
        return f"{model} is near its configured daily token budget."
    return f"{model} is near a configured quota limit."


def _quota_reference_source(model_key: str) -> str:
    if model_key in FREE_TIER_REQUEST_BUDGET_REFERENCES:
        return "google_free_tier_reference"
    if model_key in PROJECT_CONFIGURED_MODEL_BUDGET_NOTES:
        return "project_configured_ai_studio_limit"
    return "configured_budget_only"


def _quota_reference_note(model_key: str) -> str:
    if model_key in FREE_TIER_REQUEST_BUDGET_REFERENCES:
        return "Published Google Gemini API Free Tier reference for this model family."
    return PROJECT_CONFIGURED_MODEL_BUDGET_NOTES.get(
        model_key,
        "No built-in Free Tier reference is available; keep the configured budget aligned with Google AI Studio.",
    )


def _safe_warning_ratio(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_QUOTA_WARNING_RATIO
    if parsed <= 0 or parsed >= 1:
        return DEFAULT_QUOTA_WARNING_RATIO
    return parsed


def _safe_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_record_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _record_last_quota_hit(bucket: dict, created_at: datetime | None) -> None:
    if created_at is None:
        return
    previous = _parse_record_datetime(bucket.get("last_quota_hit_at"))
    if previous is None or created_at >= previous:
        bucket["last_quota_hit_at"] = created_at.isoformat()


def _attempt_cooldown_seconds(attempt: dict, *, default_seconds: float) -> float:
    value = attempt.get("cooldown_seconds")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, parsed if parsed > 0 else float(default_seconds or 0.0))


def _cooldown_remaining_seconds(
    created_at: datetime | None,
    *,
    now_utc_naive: datetime,
    cooldown_seconds: float,
) -> int:
    if created_at is None or cooldown_seconds <= 0:
        return 0
    until = created_at + timedelta(seconds=float(cooldown_seconds))
    return max(0, int((until - now_utc_naive).total_seconds()))
