from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.time import utc_now_naive
from app.db.session import session_scope
from app.services.llm_model_routing_policy import (
    configured_text_model_order,
    normalize_model_name as normalize_model_name,
)
from app.services.llm_quota_reference import (
    FREE_TIER_RATE_LIMIT_SOURCE as FREE_TIER_RATE_LIMIT_SOURCE,
    FREE_TIER_REQUEST_BUDGET_REFERENCES as FREE_TIER_REQUEST_BUDGET_REFERENCES,
    FREE_TIER_TOKEN_BUDGET_REFERENCES as FREE_TIER_TOKEN_BUDGET_REFERENCES,
    PROJECT_CONFIGURED_MODEL_BUDGET_NOTES as PROJECT_CONFIGURED_MODEL_BUDGET_NOTES,
    parse_model_budget_map as parse_model_budget_map,
    quota_reference_note,
    quota_reference_source,
)
from app.services.llm_quota_usage import (
    NON_REQUEST_ATTEMPT_OUTCOMES as NON_REQUEST_ATTEMPT_OUTCOMES,
    quota_health_by_model,
    usage_by_model,
)
from app.services.llm_usage_repository import LLMUsageRepository

DEFAULT_QUOTA_WARNING_RATIO = 0.8


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
        request_budgets = parse_model_budget_map(
            getattr(settings, "llm_model_daily_request_budgets", "")
        )
        token_budgets = parse_model_budget_map(
            getattr(settings, "llm_model_daily_token_budgets", "")
        )
        warning_ratio = _safe_warning_ratio(
            getattr(settings, "llm_quota_warning_ratio", DEFAULT_QUOTA_WARNING_RATIO)
        )
        default_cooldown_seconds = max(
            0.0,
            float(getattr(settings, "llm_model_quota_cooldown_seconds", 0.0) or 0.0),
        )
        model_order = configured_text_model_order(settings)
        usage_records = self._usage_records(window["start_utc_naive"])
        usage = usage_by_model(usage_records)
        quota_health = quota_health_by_model(
            usage_records,
            now_utc_naive=window["now_utc_naive"],
            default_cooldown_seconds=default_cooldown_seconds,
        )
        configured_by_key = {normalize_model_name(model): model for model in model_order}
        for model_key in sorted((set(usage) | set(quota_health)) - set(configured_by_key)):
            configured_by_key[model_key] = (
                usage.get(model_key, {}).get("model")
                or quota_health.get(model_key, {}).get("model")
                or model_key
            )
        rows = []
        for model_key, display_model in configured_by_key.items():
            usage_record = usage.get(model_key, {})
            quota_health_record = quota_health.get(model_key, {})
            request_budget = request_budgets.get(model_key)
            token_budget = token_budgets.get(model_key)
            requests_used = int(usage_record.get("request_count") or 0)
            tokens_used = int(usage_record.get("total_token_estimate") or 0)
            active_cooldown_seconds = int(quota_health_record.get("active_cooldown_seconds") or 0)
            request_remaining = _remaining(request_budget, requests_used)
            token_remaining = _remaining(token_budget, tokens_used)
            request_used_ratio = _used_ratio(request_budget, requests_used)
            token_used_ratio = _used_ratio(token_budget, tokens_used)
            usage_ratio = _max_ratio(request_used_ratio, token_used_ratio)
            request_exhausted = (
                request_budget is not None
                and request_remaining is not None
                and request_remaining <= 0
            )
            token_exhausted = (
                token_budget is not None and token_remaining is not None and token_remaining <= 0
            )
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
                    "configured": model_key
                    in {normalize_model_name(model) for model in model_order},
                    "rank": _rank_for_model(model_order, display_model),
                    "completion_count": int(usage_record.get("completion_count") or 0),
                    "requests_used": requests_used,
                    "request_budget": request_budget,
                    "free_tier_request_budget_reference": (
                        FREE_TIER_REQUEST_BUDGET_REFERENCES.get(model_key)
                    ),
                    "free_tier_token_budget_reference": (
                        FREE_TIER_TOKEN_BUDGET_REFERENCES.get(model_key)
                    ),
                    "quota_reference_source": quota_reference_source(model_key),
                    "quota_reference_note": quota_reference_note(model_key),
                    "requests_remaining": request_remaining,
                    "request_used_ratio": request_used_ratio,
                    "tokens_used": tokens_used,
                    "token_budget": token_budget,
                    "tokens_remaining": token_remaining,
                    "token_used_ratio": token_used_ratio,
                    "usage_ratio": usage_ratio,
                    "estimated_cost_usd": round(
                        float(usage_record.get("estimated_cost_usd") or 0.0), 6
                    ),
                    "fallback_count": int(usage_record.get("fallback_count") or 0),
                    "retryable_failure_count": int(
                        usage_record.get("retryable_failure_count") or 0
                    ),
                    "quota_hit_count": int(quota_health_record.get("quota_hit_count") or 0),
                    "quota_skip_count": int(quota_health_record.get("quota_skip_count") or 0),
                    "daily_quota_skip_count": int(
                        quota_health_record.get("daily_quota_skip_count") or 0
                    ),
                    "cooldown_skip_count": int(quota_health_record.get("cooldown_skip_count") or 0),
                    "active_cooldown_seconds": active_cooldown_seconds,
                    "last_quota_hit_at": quota_health_record.get("last_quota_hit_at"),
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
        rows.sort(
            key=lambda item: (item["rank"] if item["rank"] is not None else 999, item["model"])
        )
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
            if recommended
            and item.get("configured")
            and int(item.get("rank") or 999) < int(recommended.get("rank") or 999)
        ]
        totals = {
            "request_count": sum(int(item.get("requests_used") or 0) for item in rows),
            "completion_count": sum(int(item.get("completion_count") or 0) for item in rows),
            "total_token_estimate": sum(int(item.get("tokens_used") or 0) for item in rows),
            "estimated_cost_usd": round(
                sum(float(item.get("estimated_cost_usd") or 0.0) for item in rows), 6
            ),
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
            "recommended_routing_tier": (recommended["routing_tier"] if recommended else None),
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
                "selection_rule": "使用目前額度週期中第一個尚未用完的已設定模型。",
                "warning_rule": (
                    "用量達提醒門檻只提示風險；在設定額度用完前，路由仍優先使用較聰明模型。"
                ),
                "exhausted_before_recommendation": exhausted_before_recommendation,
                "high_quota_fallback_models": [
                    item["model"]
                    for item in rows
                    if item.get("routing_tier") == "high_quota_fallback"
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
                    "llm_model_daily_request_budgets": getattr(
                        settings, "llm_model_daily_request_budgets", ""
                    ),
                    "llm_model_daily_token_budgets": getattr(
                        settings, "llm_model_daily_token_budgets", ""
                    ),
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
            if (
                normalize_model_name(str(item.get("model_key") or item.get("model") or ""))
                == model_key
            ):
                return max(0.0, float(item.get("active_cooldown_seconds") or 0.0))
        return 0.0

    def _usage_records(self, since_utc_naive: datetime) -> list[dict]:
        with self.session_scope_factory() as session:
            repository = self.llm_usage_repository_cls(session)
            records = repository.since(since_utc_naive)
            return [repository.to_dict(record) for record in records]

    def _quota_window(self, settings: Any) -> dict:
        timezone_name = str(
            getattr(settings, "llm_quota_window_timezone", "") or "America/Los_Angeles"
        )
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
        return "已跳過此模型，直到下一個額度週期；原因是設定的每日額度已用完。"
    if status == "cooldown":
        return (
            "暫時略過此模型；最近的額度或速率限制命中仍在冷卻中，"
            f"約 {active_cooldown_seconds} 秒後恢復。"
        )
    if quota_warning:
        return "額度用完前仍可使用；送出大型批次前請先確認剩餘額度。"
    if tier == "primary":
        return "主力模型仍有額度時優先使用。"
    if tier == "high_quota_fallback":
        return "較聰明模型用完後，作為長文或低優先文字任務的高額度保底。"
    if tier == "local_fallback":
        return "雲端 provider 模型不可用時，改用本機 gateway 後援。"
    return "前序模型用完或不可用後，才使用此後援候選模型。"


def _next_action(
    *,
    status: str,
    risk_level: str,
    routing_tier: str,
    active_cooldown_seconds: int,
) -> str:
    if status == "exhausted":
        return "路由會自動降級，不需手動操作；此模型會略過到額度週期重置。"
    if status == "cooldown":
        return (
            "不需手動操作；此模型會略過到冷卻結束，"
            f"約 {active_cooldown_seconds} 秒後恢復。"
        )
    if risk_level == "warning":
        return "額度用完前可繼續使用；若需保留剩餘額度，請延後大型批次任務。"
    if routing_tier == "high_quota_fallback":
        return "保留為較聰明模型用完後的高用量保底。"
    if risk_level == "tracking_only":
        return "若此模型要參與硬路由，請設定每日額度。"
    return "目前不需立即處理。"


def _recommended_reason(
    recommended: dict | None,
    exhausted_before_recommendation: list[str],
    warning_ratio: float,
) -> str:
    if not recommended:
        return "目前額度週期中，沒有已設定模型還有可追蹤額度。"
    if not exhausted_before_recommendation and recommended.get("quota_warning"):
        percent = int(round(warning_ratio * 100))
        return f"最高順位已設定模型仍有可追蹤額度；目前已達 {percent}% 提醒門檻。"
    if not exhausted_before_recommendation:
        return "最高順位已設定模型仍有可追蹤額度。"
    skipped = ", ".join(exhausted_before_recommendation)
    return f"目前額度週期中，前序模型已用完：{skipped}。"


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


def _safe_warning_ratio(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_QUOTA_WARNING_RATIO
    if parsed <= 0 or parsed >= 1:
        return DEFAULT_QUOTA_WARNING_RATIO
    return parsed
