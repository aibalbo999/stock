from __future__ import annotations

from html import escape
from typing import Any


def empty_report_result_html(picker: dict[str, Any]) -> str:
    return f"""
        <div class="result-shell">
        <div class="section-title">{_html(picker.get("summary_title"), default="尚未選擇報告")}</div>
        <div class="section-note">{_html(picker.get("summary_detail"), default="建立分析後，這裡會顯示目前保留的最新版報告。")}</div>
    </div>
    """


def latest_report_picker_html(picker: dict[str, Any]) -> str:
    return f"""<section class="latest-report-picker is-{_html(picker.get("mode"), default="empty")}" aria-label="最新版報告範圍">
<span>{_html(picker.get("summary_title"), default="-")}</span>
<strong>{_html(picker.get("summary_detail"))}</strong>
<em class="latest-report-picker-note">{_html(picker.get("scope_note"))}</em>
</section>"""


def report_lifecycle_strip_html(lifecycle: dict[str, Any]) -> str:
    stage_html = "\n".join(
        report_lifecycle_stage_html(stage)
        for stage in lifecycle.get("stage_cards") or []
        if isinstance(stage, dict)
    )
    return f"""<section class="report-lifecycle-strip is-{_html(lifecycle.get("overall_state"), default="attention")}" aria-label="報告生命週期">
<div class="report-lifecycle-summary">
<span>報告生命週期</span>
<strong>{_html(lifecycle.get("trust_label"), default="-")}</strong>
<p>{_html(lifecycle.get("trust_explanation"))}</p>
<em>{_html(lifecycle.get("primary_action"))}</em>
<small>{_html(lifecycle.get("primary_action_detail"))}</small>
</div>
<div class="report-lifecycle-steps">
{stage_html}
</div>
</section>"""


def report_lifecycle_action_html() -> str:
    return """<section class="report-lifecycle-action" aria-label="報告生命週期操作">
<span>建議操作</span>
<strong>依照生命週期狀態開啟下一步</strong>
</section>"""


def empty_report_action_html(summary: dict[str, Any]) -> str:
    return f"""<section class="report-lifecycle-action is-{_html(summary.get("state"), default="empty")}" aria-label="報告空狀態操作">
<span>{_html(summary.get("eyebrow"), default="建議操作")}</span>
<strong>{_html(summary.get("title"))}</strong>
<em>{_html(summary.get("caption"))}</em>
</section>"""


def report_reader_decision_html(summary: dict[str, Any]) -> str:
    return f"""<section class="report-reader-decision is-{_html(summary.get("state"), default="attention")}" aria-label="報告閱讀決策摘要">
<div class="report-reader-decision-main">
<span>{_html(summary.get("eyebrow"), default="閱讀決策")}</span>
<strong>{_html(summary.get("title"))}</strong>
<p>{_html(summary.get("caption"))}</p>
</div>
<div class="report-reader-decision-grid">
<article>
<span>最新版證據</span>
<strong>{_html(summary.get("evidence"))}</strong>
</article>
<article>
<span>品質與股票</span>
<strong>{_html(summary.get("quality"))}</strong>
</article>
<article>
<span>補強</span>
<strong>{_html(summary.get("follow_up"))}</strong>
</article>
<article>
<span>下一步</span>
<strong>{_html(summary.get("action_label"))}</strong>
<em>{_html(summary.get("action_detail"))}</em>
</article>
</div>
</section>"""


def report_lifecycle_stage_html(stage: dict[str, Any]) -> str:
    return f"""<article class="report-lifecycle-step is-{_html(stage.get("state"), default="unknown")}">
<span>{_html(stage.get("title"), default="-")}</span>
<strong>{_html(stage.get("label"), default="-")}</strong>
<p>{_html(stage.get("detail"))}</p>
</article>"""


def report_health_strip_html(summary: dict[str, Any]) -> str:
    return f"""<section class="report-health-strip is-{_html(summary.get("state"), default="attention")}">
<article class="report-health-card">
<span>最新版</span>
<strong>{_html(summary.get("report_label"), default="-")}</strong>
<em>{_html(summary.get("report_meta_label"))}</em>
</article>
<article class="report-health-card">
<span>品質門檻</span>
<strong>{_html(summary.get("quality_label"), default="-")}</strong>
</article>
<article class="report-health-card">
<span>股票範圍</span>
<strong>{_html(summary.get("candidate_label"), default="-")}</strong>
</article>
<article class="report-health-card">
<span>補強狀態</span>
<strong>{_html(summary.get("follow_up_label"), default="-")}</strong>
</article>
<article class="report-health-card report-health-action is-{_html(summary.get("follow_up_state"), default="unknown")}">
<span>建議操作</span>
<strong>{_html(summary.get("action_label"), default="-")}</strong>
</article>
</section>"""


def _html(value: Any, *, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return escape(text or default)
