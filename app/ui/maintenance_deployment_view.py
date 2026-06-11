from __future__ import annotations

from html import escape


def external_deployment_focus_banner_html(banner: dict) -> str:
    return f"""<section class="maintenance-focus-banner is-{escape(str(banner.get("state", "attention")))}" aria-label="目前維護焦點">
<div>
<span>目前焦點</span>
<strong>{escape(str(banner.get("title") or "-"))}</strong>
<p>{escape(str(banner.get("detail") or ""))}</p>
</div>
<em>{escape(str(banner.get("target_caption") or ""))}</em>
</section>"""


def external_deployment_operator_summary_html(summary: dict) -> str:
    return f"""<section class="external-deployment-operator-summary is-{escape(str(summary.get("state", "ready")))}" aria-label="外部部署選配決策摘要">
<span>外部部署選配決策摘要</span>
<strong>{escape(str(summary.get("title") or "-"))}</strong>
<p>{escape(str(summary.get("detail") or ""))}</p>
<div class="external-deployment-operator-summary-grid">
  <em>{escape(str(summary.get("local_action") or "-"))}</em>
  <em>{escape(str(summary.get("effective_remaining") or "-"))}</em>
  <em>{escape(str(summary.get("paid_external") or "-"))}</em>
</div>
<small>{escape(str(summary.get("next_step") or ""))}</small>
</section>"""
