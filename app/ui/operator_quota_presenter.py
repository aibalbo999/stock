from __future__ import annotations

from typing import Any


def quota_operator_summary(quota: dict) -> dict[str, str]:
    recommended_model = _text(quota.get("recommended_model"), default="-")
    recommended_row = _recommended_quota_row(quota, recommended_model)
    remaining = _quota_remaining_text(recommended_row)
    state = _quota_state(recommended_row)
    model_order_label = _model_order_label(quota)
    limited_model_label = _limited_model_label(_first_limited_quota_model(quota))
    fallback_models = _high_quota_fallback_models(quota)
    high_quota_fallback_label = (
        "高額度保底：" + "、".join(fallback_models) if fallback_models else "無高額度保底模型"
    )
    next_model_label = _next_quota_model_label(quota, recommended_model)
    operator_caption = _quota_operator_card_caption(
        remaining=remaining,
        next_model_label=next_model_label,
        limited_model_label=limited_model_label,
        high_quota_fallback_models=fallback_models,
    )
    caption = "｜".join(
        label for label in [model_order_label, limited_model_label, high_quota_fallback_label] if label
    )
    return {
        "recommended_model": recommended_model,
        "remaining": remaining,
        "state": state,
        "model_order_label": model_order_label,
        "limited_model_label": limited_model_label,
        "high_quota_fallback_label": high_quota_fallback_label,
        "next_model_label": next_model_label,
        "operator_caption": operator_caption,
        "caption": caption,
    }


def _recommended_quota_row(quota: dict, recommended_model: str) -> dict:
    if not isinstance(quota, dict):
        return {}
    for row in quota.get("models") or []:
        if not isinstance(row, dict):
            continue
        if _text(row.get("model")) == recommended_model:
            return row
    return {}


def _quota_remaining_text(model_row: dict) -> str:
    remaining = model_row.get("requests_remaining") if isinstance(model_row, dict) else None
    budget = model_row.get("request_budget") if isinstance(model_row, dict) else None
    if remaining in {None, ""} or budget in {None, ""}:
        return "額度未追蹤"
    return f"{remaining} / {budget}"


def _quota_state(model_row: dict) -> str:
    if not isinstance(model_row, dict) or not model_row:
        return "attention"
    status = _text(model_row.get("status")).casefold()
    if status in {"ready", "available", "ok"}:
        return "ready"
    remaining = model_row.get("requests_remaining")
    try:
        return "ready" if int(remaining) > 0 else "attention"
    except (TypeError, ValueError):
        return "attention"


def _high_quota_fallback_models(quota: dict) -> list[str]:
    if not isinstance(quota, dict):
        return []
    model_rows = quota.get("models")
    if isinstance(model_rows, list):
        models = [
            _text(row.get("model"))
            for row in model_rows
            if isinstance(row, dict)
            and _text(row.get("routing_tier")) == "high_quota_fallback"
        ]
        models = [model for model in models if model]
        if models:
            return models

    routing_policy = quota.get("routing_policy")
    if not isinstance(routing_policy, dict):
        return []
    return [
        model
        for model in (_text(item) for item in routing_policy.get("high_quota_fallback_models") or [])
        if model
    ]


def _next_quota_model_label(quota: dict, recommended_model: str) -> str:
    models = _model_order(quota)
    if not recommended_model or recommended_model not in models:
        return ""
    next_index = models.index(recommended_model) + 1
    if next_index >= len(models):
        return ""
    return f"下一順位 {models[next_index]}"


def _quota_operator_card_caption(
    *,
    remaining: str,
    next_model_label: str,
    limited_model_label: str,
    high_quota_fallback_models: list[str],
) -> str:
    remaining_label = (
        f"免費額度 {remaining}" if remaining and remaining != "額度未追蹤" else "額度未追蹤"
    )
    labels = ["聰明優先", remaining_label]
    if next_model_label:
        labels.append(next_model_label)
    if limited_model_label and limited_model_label != "受限：無":
        labels.append(limited_model_label)
    if high_quota_fallback_models:
        labels.append("保底 " + "、".join(high_quota_fallback_models))
    return "｜".join(labels)


def _model_order_label(quota: dict) -> str:
    models = _model_order(quota)
    if not models:
        return "順序：尚無模型順序"
    visible_models = models[:4]
    suffix = f" +{len(models) - len(visible_models)}" if len(models) > len(visible_models) else ""
    return "順序：" + " → ".join(visible_models) + suffix


def _model_order(quota: dict) -> list[str]:
    if not isinstance(quota, dict):
        return []
    explicit_order = [_text(model) for model in quota.get("model_order") or []]
    explicit_order = [model for model in explicit_order if model]
    if explicit_order:
        return list(dict.fromkeys(explicit_order))

    rows = [
        row
        for row in quota.get("models") or []
        if isinstance(row, dict) and _text(row.get("model"))
    ]
    rows.sort(key=lambda row: (_rank_value(row.get("rank")), _text(row.get("model"))))
    return list(dict.fromkeys(_text(row.get("model")) for row in rows))


def _first_limited_quota_model(quota: dict) -> dict:
    if not isinstance(quota, dict):
        return {}
    ordered_models = _model_order(quota)
    rows_by_model = {
        _text(row.get("model")): row
        for row in quota.get("models") or []
        if isinstance(row, dict) and _text(row.get("model"))
    }
    for model in ordered_models:
        row = rows_by_model.get(model, {})
        if _quota_limited_status(row):
            return row

    limited_rows = [
        row
        for row in quota.get("models") or []
        if isinstance(row, dict) and _quota_limited_status(row)
    ]
    limited_rows.sort(key=lambda row: (_rank_value(row.get("rank")), _text(row.get("model"))))
    return limited_rows[0] if limited_rows else {}


def _quota_limited_status(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    status = _text(row.get("status")).casefold()
    if status in {"exhausted", "cooldown"}:
        return status
    risk_level = _text(row.get("risk_level")).casefold()
    if risk_level in {"exhausted", "cooldown"}:
        return risk_level
    return ""


def _limited_model_label(row: dict) -> str:
    status = _quota_limited_status(row)
    if not status:
        return "受限：無"
    model = _text(row.get("model"), default="-")
    if status == "cooldown":
        seconds = _int_value(row.get("active_cooldown_seconds"))
        return f"受限：{model}（冷卻 {seconds} 秒）"
    return f"受限：{model}（耗盡）"


def _rank_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999


def _text(value: Any, *, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
