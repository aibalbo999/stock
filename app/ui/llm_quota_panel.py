from __future__ import annotations

from datetime import datetime
from typing import Any


MODEL_STATUS_LABELS = {
    "available": "可用",
    "ready": "可用",
    "ok": "可用",
    "near_limit": "接近額度上限",
    "warning": "需注意",
    "exhausted": "額度用完",
    "cooldown": "冷卻中",
    "unavailable": "不可用",
    "unknown": "未知",
}

RISK_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "exhausted": "額度用完",
    "cooldown": "冷卻中",
    "unknown": "未知",
}

ROUTING_TIER_LABELS = {
    "primary": "主力模型",
    "fallback": "後援模型",
    "high_quota_fallback": "高額度保底",
    "disabled": "停用",
}

STATUS_REASON_LABELS = {
    "request_budget_exhausted": "請求額度已用完",
    "within_configured_budget": "仍在設定額度內",
    "active_cooldown": "冷卻中",
    "quota_or_cooldown_skip": "額度或冷卻略過",
    "no_usage_record": "尚無用量紀錄",
    "token_budget_exhausted": "Token 額度已用完",
}

QUOTA_REFERENCE_LABELS = {
    "project_configured_ai_studio_limit": "專案設定的 AI Studio 限制",
    "official_free_tier_reference": "官方 Free Tier 參考",
    "manual_override": "手動覆寫",
}

ROUTING_REASON_LABELS = {
    "Skipped until the next quota window.": "跳過到下一個額度週期。",
    "No action needed for routing.": "路由會自動降級，不需手動操作。",
}

RECOMMENDED_REASON_LABELS = {
    "Earlier model(s) exhausted.": "前序模型額度已用完，已自動改用下一順位。",
    (
        "Top-ranked configured model still has remaining tracked quota; "
        "it has reached the 80% warning threshold."
    ): "最高順位模型仍有追蹤額度，已接近 80% 提醒門檻。",
}

BUDGET_NOTE_LABELS = {
    "Limits are project-level.": "額度限制以專案層級為準。",
}

ALERT_SEVERITY_LABELS = {
    "error": "需處理",
    "warning": "需注意",
    "info": "資訊",
}

ALERT_ACTION_LABELS = {
    "Keep using this model until exhausted.": "保持目前模型，直到額度用完再自動降級。",
    "No manual action needed.": "不需手動操作。",
    "No action needed for routing.": "路由會自動降級，不需手動操作。",
}


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
                "順位": model.get("rank"),
                "模型": model.get("model"),
                "狀態": _label(MODEL_STATUS_LABELS, model.get("status")),
                "風險": _label(RISK_LABELS, model.get("risk_level")),
                "路由層級": _label(ROUTING_TIER_LABELS, model.get("routing_tier")),
                "狀態原因": _label(STATUS_REASON_LABELS, model.get("status_reason")),
                "路由原因": _label(ROUTING_REASON_LABELS, model.get("routing_reason")),
                "今日請求": _format_budget(
                    model.get("requests_used"),
                    model.get("request_budget"),
                ),
                "Free Tier 參考": _display_value(
                    model.get("free_tier_request_budget_reference")
                ),
                "額度來源": _label(
                    QUOTA_REFERENCE_LABELS,
                    model.get("quota_reference_source"),
                ),
                "剩餘請求": _display_value(model.get("requests_remaining")),
                "請求用量": _format_ratio(model.get("request_used_ratio")),
                "今日 Token": _format_budget(
                    model.get("tokens_used"),
                    model.get("token_budget"),
                ),
                "剩餘 Token": _display_value(model.get("tokens_remaining")),
                "Token 用量": _format_ratio(model.get("token_used_ratio")),
                "後援次數": _display_value(model.get("fallback_count")),
                "可重試失敗": _display_value(model.get("retryable_failure_count")),
                "額度命中": _display_value(model.get("quota_hit_count")),
                "額度略過": _display_value(model.get("quota_skip_count")),
                "日額度略過": _display_value(model.get("daily_quota_skip_count")),
                "冷卻略過": _display_value(model.get("cooldown_skip_count")),
                "冷卻剩餘": _display_value(
                    _format_duration(model.get("active_cooldown_seconds"))
                ),
                "最近額度命中": _display_value(model.get("last_quota_hit_at")),
                "下一步": _label(ROUTING_REASON_LABELS, model.get("next_action")),
            }
        )
    return rows


def llm_quota_captions(llm_quota: dict) -> list[str]:
    captions = []
    recommendation = _recommendation_caption(llm_quota)
    if recommendation:
        captions.append(recommendation)
    if llm_quota.get("recommended_reason"):
        captions.append(_label(RECOMMENDED_REASON_LABELS, llm_quota["recommended_reason"]))
    captions.extend(_quota_alert_captions(llm_quota))
    budget_source = _dict_value(llm_quota.get("budget_source"))
    if budget_source.get("note"):
        captions.append(_label(BUDGET_NOTE_LABELS, budget_source["note"]))
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
            f"{model.get('model')} 設定 {configured_int} / 官方 {reference_int}"
        )
    if not drift_rows:
        return []
    return [
        "Free Tier 參考差異："
        + "；".join(drift_rows[:3])
        + "。實際仍以 Google AI Studio 專案額度為準。"
    ]


def _quota_alert_captions(llm_quota: dict) -> list[str]:
    captions = []
    for alert in llm_quota.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        model = str(alert.get("model") or "-")
        severity = _label(ALERT_SEVERITY_LABELS, alert.get("severity") or "warning")
        ratio = _format_ratio(alert.get("usage_ratio"))
        cooldown = _format_duration(alert.get("active_cooldown_seconds"))
        raw_next_action = str(alert.get("next_action") or "").strip()
        next_action = (
            _label(ALERT_ACTION_LABELS, raw_next_action) if raw_next_action else ""
        )
        caption = f"額度提醒：{model} {severity}"
        if ratio != "-":
            caption += f"（已用 {ratio}）"
        if cooldown:
            caption += f"；冷卻約 {cooldown}"
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
        parts.append(f"路由層級 {_label(ROUTING_TIER_LABELS, tier)}")
    window = _dict_value(llm_quota.get("window"))
    reset_in_seconds = window.get("reset_in_seconds")
    reset_text = _format_duration(reset_in_seconds)
    if reset_text:
        parts.append(f"約 {reset_text} 後重置")
    return "｜".join(parts)


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _label(labels: dict[str, str], value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    return labels.get(text, text)


def _display_value(value: Any) -> Any:
    if value is None:
        return "-"
    if isinstance(value, str) and not value.strip():
        return "-"
    return value


def _format_budget(used: Any, budget: Any) -> str:
    used_display = _display_budget_value(used, zero_when_missing=True)
    budget_display = _display_budget_value(budget)
    return f"{used_display} / {budget_display}"


def _display_budget_value(value: Any, *, zero_when_missing: bool = False) -> Any:
    if value is None:
        return 0 if zero_when_missing else "-"
    if isinstance(value, str) and not value.strip():
        return 0 if zero_when_missing else "-"
    return value


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
