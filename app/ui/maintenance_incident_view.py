from __future__ import annotations

from html import escape


def incident_inbox_header_html(badges: list[str]) -> str:
    count_badges = "\n".join(f"<span>{escape(label)}</span>" for label in badges)
    return f"""<section class="incident-inbox" aria-label="待處理事件">
<div class="incident-inbox-head">
<div>
<div class="workspace-kicker">待處理事件</div>
<h3>事件收件匣</h3>
</div>
<div class="incident-counts">
{count_badges}
</div>
</div>
</section>"""


def incident_list_html(incident_html: str) -> str:
    return f"""<section class="incident-inbox is-list" aria-label="事件清單">
<div class="incident-list">
{incident_html}
</div>
</section>"""


def incident_empty_card_html() -> str:
    return """<article class="incident-card is-ready">
<strong>目前沒有待處理事件</strong>
<span>背景任務、近期失敗與 AI 額度沒有主要阻塞。</span>
</article>"""


def incident_priority_summary_html(summary: dict[str, object]) -> str:
    state = escape(str(summary.get("state") or "ready"))
    return f"""<section class="incident-priority-summary is-{state}" aria-label="事件可行動摘要">
<div>
<span>建議處理順序</span>
<strong>{escape(str(summary.get("title") or ""))}</strong>
<p>{escape(str(summary.get("counts_label") or ""))}</p>
</div>
<ul>
<li>{escape(str(summary.get("primary_action") or ""))}</li>
<li>{escape(str(summary.get("secondary_action") or ""))}</li>
</ul>
</section>"""


def incident_action_controls_intro_html() -> str:
    return """<section class="incident-action-controls" aria-label="事件處理操作">
<span>處理事件</span>
<strong>開啟對應頁面或任務檢視</strong>
</section>"""


def incident_card_html(incident: dict, *, route_text: str = "") -> str:
    repeat_count = _incident_count_value(incident.get("repeat_count"), default=1)
    repeat_badge = ""
    if repeat_count > 1:
        repeat_badge = (
            f'<span class="incident-repeat-badge">同類事件 {escape(str(repeat_count))} 筆</span>'
        )
    return f"""<article class="incident-card is-{escape(str(incident.get("severity") or "info"))}">
<div class="incident-card-head">
<strong>{escape(str(incident.get("title") or "-"))}</strong>
{repeat_badge}
</div>
<span>{escape(str(incident.get("impact") or ""))}</span>
<em>{escape(str(incident.get("next_action") or ""))}</em>
<small>{escape(route_text)}</small>
</article>"""


def _incident_count_value(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)
