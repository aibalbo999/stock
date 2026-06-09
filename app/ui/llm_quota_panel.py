from __future__ import annotations

from datetime import datetime
from typing import Any


def llm_quota_metric_values(llm_quota: dict) -> dict[str, str | int]:
    window = _dict_value(llm_quota.get("window"))
    totals = _dict_value(llm_quota.get("totals"))
    return {
        "推薦模型": str(llm_quota.get("recommended_model") or "-"),
        "今日請求": int(totals.get("request_count") or 0),
        "今日 Token": int(totals.get("total_token_estimate") or 0),
        "額度重置": _format_window_end(window.get("end")),
    }


def llm_quota_model_rows(llm_quota: dict) -> list[dict]:
    rows = []
    for model in llm_quota.get("models") or []:
        if not isinstance(model, dict):
            continue
        rows.append(
            {
                "rank": model.get("rank"),
                "model": model.get("model"),
                "status": model.get("status"),
                "risk": model.get("risk_level"),
                "tier": model.get("routing_tier"),
                "reason": model.get("status_reason"),
                "routing_reason": model.get("routing_reason"),
                "requests_used": model.get("requests_used"),
                "request_budget": model.get("request_budget"),
                "free_tier_request_budget": model.get("free_tier_request_budget_reference"),
                "quota_reference": model.get("quota_reference_source"),
                "requests_remaining": model.get("requests_remaining"),
                "request_used_pct": _format_ratio(model.get("request_used_ratio")),
                "tokens_used": model.get("tokens_used"),
                "token_budget": model.get("token_budget"),
                "tokens_remaining": model.get("tokens_remaining"),
                "token_used_pct": _format_ratio(model.get("token_used_ratio")),
                "fallback_count": model.get("fallback_count"),
                "retryable_failure_count": model.get("retryable_failure_count"),
                "quota_hit_count": model.get("quota_hit_count"),
                "quota_skip_count": model.get("quota_skip_count"),
                "daily_quota_skip_count": model.get("daily_quota_skip_count"),
                "cooldown_skip_count": model.get("cooldown_skip_count"),
                "active_cooldown": _format_duration(model.get("active_cooldown_seconds")),
                "last_quota_hit_at": model.get("last_quota_hit_at"),
                "next_action": model.get("next_action"),
            }
        )
    return rows


def llm_quota_captions(llm_quota: dict) -> list[str]:
    captions = []
    recommendation = _recommendation_caption(llm_quota)
    if recommendation:
        captions.append(recommendation)
    if llm_quota.get("recommended_reason"):
        captions.append(str(llm_quota["recommended_reason"]))
    captions.extend(_quota_alert_captions(llm_quota))
    budget_source = _dict_value(llm_quota.get("budget_source"))
    if budget_source.get("note"):
        captions.append(str(budget_source["note"]))
    captions.extend(_quota_reference_drift_captions(llm_quota))
    routing_policy = _dict_value(llm_quota.get("routing_policy"))
    high_quota_models = [
        str(model)
        for model in routing_policy.get("high_quota_fallback_models") or []
        if str(model).strip()
    ]
    if high_quota_models:
        captions.append("高額度保底模型：" + "、".join(high_quota_models))
    return captions


def _quota_reference_drift_captions(llm_quota: dict) -> list[str]:
    drift_rows = []
    for model in llm_quota.get("models") or []:
        if not isinstance(model, dict):
            continue
        configured = model.get("request_budget")
        reference = model.get("free_tier_request_budget_reference")
        if configured in {None, ""} or reference in {None, ""}:
            continue
        try:
            configured_int = int(configured)
            reference_int = int(reference)
        except (TypeError, ValueError):
            continue
        if configured_int == reference_int:
            continue
        drift_rows.append(
            f"{model.get('model')}: configured {configured_int} / official {reference_int}"
        )
    if not drift_rows:
        return []
    return [
        "Free Tier 參考差異："
        + "；".join(drift_rows[:3])
        + "。實際仍以 Google AI Studio project limit 為準。"
    ]


def _quota_alert_captions(llm_quota: dict) -> list[str]:
    captions = []
    for alert in llm_quota.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        model = str(alert.get("model") or "-")
        severity = str(alert.get("severity") or "warning")
        ratio = _format_ratio(alert.get("usage_ratio"))
        cooldown = _format_duration(alert.get("active_cooldown_seconds"))
        next_action = str(alert.get("next_action") or "").strip()
        caption = f"額度提醒：{model} {severity}"
        if ratio != "-":
            caption += f"（已用 {ratio}）"
        if cooldown:
            caption += f"；cooldown 約 {cooldown}"
        if next_action:
            caption += f"；{next_action}"
        captions.append(caption)
    return captions[:3]


def _recommendation_caption(llm_quota: dict) -> str:
    recommended = str(llm_quota.get("recommended_model") or "").strip()
    if not recommended:
        return ""
    parts = [f"目前推薦：{recommended}"]
    rank = llm_quota.get("recommended_rank")
    if rank not in {None, ""}:
        parts.append(f"順位 {rank}")
    tier = str(llm_quota.get("recommended_routing_tier") or "").strip()
    if tier:
        parts.append(f"tier={tier}")
    window = _dict_value(llm_quota.get("window"))
    reset_in_seconds = window.get("reset_in_seconds")
    reset_text = _format_duration(reset_in_seconds)
    if reset_text:
        parts.append(f"約 {reset_text} 後重置")
    return "｜".join(parts)


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _format_duration(value: Any) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} 小時 {minutes} 分鐘"
    if minutes:
        return f"{minutes} 分鐘"
    return f"{seconds} 秒"


def _format_ratio(value: Any) -> str:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{ratio * 100:.1f}%"


def _format_window_end(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    timezone = parsed.tzname() or ""
    suffix = f" {timezone}" if timezone else ""
    return parsed.strftime("%m-%d %H:%M") + suffix
