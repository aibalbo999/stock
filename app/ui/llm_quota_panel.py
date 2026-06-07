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
                "tier": model.get("routing_tier"),
                "reason": model.get("status_reason"),
                "routing_reason": model.get("routing_reason"),
                "requests_used": model.get("requests_used"),
                "request_budget": model.get("request_budget"),
                "requests_remaining": model.get("requests_remaining"),
                "tokens_used": model.get("tokens_used"),
                "token_budget": model.get("token_budget"),
                "tokens_remaining": model.get("tokens_remaining"),
                "fallback_count": model.get("fallback_count"),
                "retryable_failure_count": model.get("retryable_failure_count"),
            }
        )
    return rows


def llm_quota_captions(llm_quota: dict) -> list[str]:
    captions = []
    if llm_quota.get("recommended_reason"):
        captions.append(str(llm_quota["recommended_reason"]))
    budget_source = _dict_value(llm_quota.get("budget_source"))
    if budget_source.get("note"):
        captions.append(str(budget_source["note"]))
    routing_policy = _dict_value(llm_quota.get("routing_policy"))
    high_quota_models = [
        str(model)
        for model in routing_policy.get("high_quota_fallback_models") or []
        if str(model).strip()
    ]
    if high_quota_models:
        captions.append("高額度保底模型：" + "、".join(high_quota_models))
    return captions


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


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
