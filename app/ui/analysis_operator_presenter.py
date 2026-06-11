from __future__ import annotations

from html import escape

from app.ui.operator_routes import operator_route_target


def latest_report_id(reports: list[dict]) -> int | None:
    for report in reports:
        if not isinstance(report, dict) or report.get("id") is None:
            continue
        try:
            return int(report["id"])
        except (TypeError, ValueError):
            return None
    return None


def operator_decision_html(
    primary_action: dict,
    secondary_actions: list[dict],
    *,
    include_secondary: bool = True,
) -> str:
    secondary_block = (
        operator_secondary_actions_html(secondary_actions)
        if include_secondary and secondary_actions
        else ""
    )
    source_ids = primary_action.get("source_ids") or []
    source_text = operator_source_text(source_ids)
    target = operator_route_target(primary_action.get("route_hint"))
    target_caption = str(target.get("caption") or "")
    return f"""<section class="operator-decision-card is-{escape(primary_action.get("state", "attention"))}">
<div class="operator-decision-copy">
<div class="workspace-kicker">下一步建議</div>
<h3>{escape(primary_action.get("title", "-"))}</h3>
<p>{escape(primary_action.get("reason", ""))}</p>
<div class="operator-decision-meta">
<span>風險：{escape(primary_action.get("risk", ""))}</span>
<span>影響：{escape(primary_action.get("impact", ""))}</span>
<span>來源：{escape(source_text)}</span>
</div>
</div>
<div class="operator-decision-action">
<strong>{escape(primary_action.get("action_label", "-"))}</strong>
<span>{escape(target_caption)}</span>
</div>
{secondary_block}
</section>"""


def operator_secondary_actions_html(secondary_actions: list[dict]) -> str:
    secondary_html = "\n".join(secondary_action_html(action) for action in secondary_actions)
    return f"""<div class="operator-secondary-actions" aria-label="次要建議">
{secondary_html}
</div>"""


def operator_source_text(source_ids: object) -> str:
    if not isinstance(source_ids, list) or not source_ids:
        return "系統狀態"
    labels = []
    for source_id in source_ids:
        source_text = str(source_id).strip()
        if not source_text:
            continue
        source_label = operator_source_label(source_text)
        if source_label:
            labels.append(source_label)
        elif looks_like_operator_route(source_text):
            labels.append(str(operator_route_target(source_text).get("caption") or source_text))
        else:
            labels.append(source_text)
    return "、".join(labels) if labels else "系統狀態"


def operator_source_label(value: str) -> str:
    if value == "services_status":
        return "系統狀態"
    if value == "optimization:auto_local_defaults":
        return "本機 defaults 優化缺口"
    if value == "optimization:company_filing_structured_api_fallback":
        return "公司文件結構化 API 選配"
    if value.startswith("optimization:"):
        return "優化目標缺口"
    return ""


def looks_like_operator_route(value: str) -> bool:
    return bool(
        value in {"analysis", "data_enrichment", "report_center"}
        or value.startswith(("report:", "task:", "settings:", "data_enrichment:"))
    )


def secondary_action_html(action: dict) -> str:
    target = operator_route_target(action.get("route_hint"))
    target_caption = str(target.get("caption") or "")
    return f"""<article class="operator-secondary-action is-{escape(action.get("state", "attention"))}">
<strong>{escape(action.get("title", "-"))}</strong>
<span>{escape(action.get("detail", ""))}</span>
<em>{escape(target_caption)}</em>
</article>"""


def operator_card_html(card: dict[str, str]) -> str:
    return f"""<article class="operator-status-card is-{escape(card.get("state", "attention"))}">
<div class="operator-card-title">{escape(card.get("title", "-"))}</div>
<div class="operator-card-value">{escape(card.get("value", "-"))}</div>
<div class="operator-card-caption">{escape(card.get("caption", ""))}</div>
<div class="operator-card-action">{escape(card.get("action_label", ""))}</div>
</article>"""
