from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.db.session import session_scope
from app.services.persistence import LLMUsageRepository


class LLMQuotaGovernanceService:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any] = get_settings,
        session_scope_factory: Callable = session_scope,
        llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
        clock: Callable[[], datetime] = datetime.utcnow,
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
        model_order = self._model_order(settings)
        usage_records = self._usage_records(window["start_utc_naive"])
        usage_by_model = self._usage_by_model(usage_records)
        configured_by_key = {normalize_model_name(model): model for model in model_order}
        for model_key in sorted(set(usage_by_model) - set(configured_by_key)):
            configured_by_key[model_key] = usage_by_model[model_key].get("model") or model_key
        rows = []
        for model_key, display_model in configured_by_key.items():
            usage = usage_by_model.get(model_key, {})
            request_budget = request_budgets.get(model_key)
            token_budget = token_budgets.get(model_key)
            requests_used = int(usage.get("request_count") or 0)
            tokens_used = int(usage.get("total_token_estimate") or 0)
            request_remaining = _remaining(request_budget, requests_used)
            token_remaining = _remaining(token_budget, tokens_used)
            request_exhausted = request_budget is not None and request_remaining is not None and request_remaining <= 0
            token_exhausted = token_budget is not None and token_remaining is not None and token_remaining <= 0
            has_budget = request_budget is not None or token_budget is not None
            rows.append(
                {
                    "model": display_model,
                    "model_key": model_key,
                    "configured": model_key in {normalize_model_name(model) for model in model_order},
                    "rank": _rank_for_model(model_order, display_model),
                    "requests_used": requests_used,
                    "request_budget": request_budget,
                    "requests_remaining": request_remaining,
                    "tokens_used": tokens_used,
                    "token_budget": token_budget,
                    "tokens_remaining": token_remaining,
                    "estimated_cost_usd": round(float(usage.get("estimated_cost_usd") or 0.0), 6),
                    "fallback_count": int(usage.get("fallback_count") or 0),
                    "retryable_failure_count": int(usage.get("retryable_failure_count") or 0),
                    "status": "exhausted"
                    if request_exhausted or token_exhausted
                    else "available"
                    if has_budget
                    else "tracking_only",
                }
            )
        rows.sort(key=lambda item: (item["rank"] if item["rank"] is not None else 999, item["model"]))
        recommended = next((item for item in rows if item["configured"] and item["status"] != "exhausted"), None)
        totals = {
            "request_count": sum(int(item.get("requests_used") or 0) for item in rows),
            "total_token_estimate": sum(int(item.get("tokens_used") or 0) for item in rows),
            "estimated_cost_usd": round(sum(float(item.get("estimated_cost_usd") or 0.0) for item in rows), 6),
        }
        return {
            "window": {
                "timezone": window["timezone"],
                "start": window["start_local"].isoformat(),
                "end": window["end_local"].isoformat(),
            },
            "model_order": model_order,
            "recommended_model": recommended["model"] if recommended else None,
            "models": rows,
            "totals": totals,
            "budget_source": {
                "request_budgets_configured": bool(request_budgets),
                "token_budgets_configured": bool(token_budgets),
                "settings": {
                    "llm_model_daily_request_budgets": getattr(settings, "llm_model_daily_request_budgets", ""),
                    "llm_model_daily_token_budgets": getattr(settings, "llm_model_daily_token_budgets", ""),
                },
                "note": (
                    "Gemini API free-tier limits are project-level and can vary by model/version; "
                    "update these settings to match the limits shown in Google AI Studio."
                ),
            },
        }

    def exhausted_model_keys(self) -> set[str]:
        return {
            str(item.get("model_key") or "")
            for item in self.summary().get("models", [])
            if item.get("status") == "exhausted" and item.get("model_key")
        }

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
            bucket = usage.setdefault(
                model_key,
                {
                    "model": model,
                    "request_count": 0,
                    "total_token_estimate": 0,
                    "estimated_cost_usd": 0.0,
                    "fallback_count": 0,
                    "retryable_failure_count": 0,
                },
            )
            bucket["request_count"] += 1
            bucket["total_token_estimate"] += int(record.get("total_token_estimate") or 0)
            bucket["estimated_cost_usd"] += float(record.get("estimated_cost_usd") or 0.0)
            bucket["fallback_count"] += 1 if record.get("fallback") else 0
            bucket["retryable_failure_count"] += int(record.get("retryable_failure_count") or 0)
        return usage

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
            "start_local": start_local,
            "end_local": end_local,
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


def _remaining(budget: int | None, used: int) -> int | None:
    if budget is None:
        return None
    return max(0, int(budget) - int(used))


def _rank_for_model(model_order: list[str], model: str) -> int | None:
    model_key = normalize_model_name(model)
    for index, candidate in enumerate(model_order, start=1):
        if normalize_model_name(candidate) == model_key:
            return index
    return None
