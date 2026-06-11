from __future__ import annotations

from html import escape


def optimization_progress_scope_summary_html(summary: dict[str, object]) -> str:
    if not summary:
        return ""
    return f"""<section class="optimization-progress-scope-summary is-{_html(summary.get("state"), "info")}" aria-label="優化進度範圍說明">
<div>
<span>範圍說明</span>
<strong>{_html(summary.get("title"))}</strong>
<p>{_html(summary.get("detail"))}</p>
</div>
<ul>
<li>{_html(summary.get("objective"))}</li>
<li>{_html(summary.get("audit"))}</li>
<li>{_html(summary.get("excluded"))}</li>
</ul>
<p>{_html(summary.get("note"))}</p>
</section>"""


def optimization_progress_operator_summary_html(summary: dict[str, object]) -> str:
    if not summary:
        return ""
    command = str(summary.get("command") or "-").strip()
    command_html = ""
    if command and command != "-":
        command_html = f"<code>{escape(command)}</code>"
    action_items = [
        str(summary.get("local_action") or "").strip(),
        str(summary.get("paid_external") or "").strip(),
        str(summary.get("free_validation") or "").strip(),
        str(summary.get("next_step") or "").strip(),
    ]
    action_items_html = "".join(
        f"<li>{escape(item)}</li>" for item in action_items if item
    )
    return f"""<section class="optimization-progress-operator-summary is-{_html(summary.get("state"), "ready")}" aria-label="優化進度操作者摘要">
<div>
<span>操作者摘要</span>
<strong>{_html(summary.get("title"))}</strong>
<p>{_html(summary.get("detail"))}</p>
</div>
<ul>
{action_items_html}
</ul>
{command_html}
</section>"""


def _html(value: object, default: str = "") -> str:
    return escape(str(value if value is not None else default))
