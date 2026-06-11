from __future__ import annotations

from html import escape
from typing import Any


def scope_source_summary_html(summary: dict[str, Any]) -> str:
    return f"""<section class="scope-source-summary is-{escape(str(summary.get("state", "ready")))}" aria-label="白名單來源摘要">
  <span>白名單來源摘要</span>
  <strong>{escape(str(summary.get("title", "")))}</strong>
  <p>{escape(str(summary.get("detail", "")))}</p>
  <em>{escape(str(summary.get("source", "")))}</em>
  <small>{escape(str(summary.get("next_step", "")))}</small>
  <small>{escape(str(summary.get("fallback_hint", "")))}</small>
</section>"""
