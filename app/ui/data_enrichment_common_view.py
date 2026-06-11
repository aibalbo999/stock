from __future__ import annotations

from html import escape


def allowlist_scope_summary_html(summary: dict[str, str]) -> str:
    return f"""<section class="allowlist-scope-summary is-{escape(summary.get("state", "attention"))}" aria-label="資料補強白名單來源摘要">
<span>白名單來源摘要</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
</section>"""


def data_task_followup_summary_html(summary: dict[str, str]) -> str:
    return f"""<section class="data-task-followup-summary is-{escape(summary.get("state", "attention"))}" aria-label="資料任務後續處理">
<span>後續處理</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
</section>"""


def data_ingest_submission_summary_html(summary: dict[str, str]) -> str:
    return f"""<section class="data-ingest-submission-summary is-{escape(summary.get("state", "attention"))}" aria-label="資料送出前摘要">
<span>資料送出前摘要</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
<small>{escape(summary.get("quota_hint", ""))}</small>
</section>"""
