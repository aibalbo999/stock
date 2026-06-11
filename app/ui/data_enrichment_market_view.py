from __future__ import annotations

from html import escape

from app.ui.data_gap_actions import data_gap_action_summary


def data_gap_action_map_html(items: list[dict]) -> str:
    summary = data_gap_action_summary(items)
    cards_html = "\n".join(data_gap_action_card_html(item) for item in items[:6])
    if not cards_html:
        cards_html = """<article class="data-gap-action-card is-ready">
<strong>目前沒有必要資料缺口</strong>
<span>最新版報告沒有必補資料行動。</span>
<em>可依例行需求刷新市場資料。</em>
</article>"""
    return f"""<section class="data-gap-action-map is-{escape(summary.get("state", "ready"))}" aria-label="資料缺口行動地圖">
<div class="data-gap-action-head">
<div class="workspace-kicker">資料缺口行動地圖</div>
<h3>{escape(summary.get("label", "-"))}</h3>
<p>{escape(summary.get("detail", ""))}</p>
</div>
<div class="data-gap-action-list">
{cards_html}
</div>
</section>"""


def data_gap_action_card_html(item: dict) -> str:
    return f"""<article class="data-gap-action-card is-{escape(item.get("purpose", "tracking"))}">
<strong>{escape(item.get("action_label", "-"))}</strong>
<span>{escape(item.get("ticker", "全部"))}｜{escape(item.get("impact", ""))}</span>
<em>{escape(item.get("post_action_hint", ""))}</em>
</article>"""


def data_gap_action_controls_html() -> str:
    return """<div class="data-gap-action-controls" aria-label="資料缺口快捷處理">
<span>可直接處理</span>
<strong>選一個缺口開始補強</strong>
</div>"""


def market_allowlist_warning_html(selection_state: dict[str, str]) -> str:
    return f"""<section class="market-allowlist-warning is-{escape(selection_state.get("state", "attention"))}" aria-label="白名單提醒">
<span>白名單提醒</span>
<strong>{escape(str(selection_state.get("detail") or ""))}</strong>
</section>"""


def pending_market_handoff_html(summary: dict[str, str]) -> str:
    if not summary:
        return ""
    rejected_html = ""
    if summary.get("rejected_detail"):
        rejected_html = f"<small>{escape(summary['rejected_detail'])}</small>"
    return f"""<section class="market-handoff-banner is-{escape(summary.get("state", "ready"))}" aria-label="資料補強交接">
<div>
<span>補強導引</span>
<strong>{escape(summary.get("title", "已帶入資料補強"))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
{rejected_html}
</div>
<em>{escape(summary.get("next_step", ""))}</em>
</section>"""


def market_operation_readiness_html(rows: list[dict[str, str]]) -> str:
    cards_html = "\n".join(market_operation_readiness_card_html(row) for row in rows)
    return f"""<section class="market-operation-readiness" aria-label="資料補強執行前檢查">
<div class="market-operation-readiness-head">
<div class="workspace-kicker">執行前檢查</div>
<h3>先確認能否送出背景任務</h3>
<p>每個刷新操作會先檢查背景任務、股票、日期與目前建議操作；可送出時再按下方按鈕。</p>
</div>
<div class="market-operation-readiness-list">
{cards_html}
</div>
</section>"""


def market_operation_readiness_card_html(row: dict[str, str]) -> str:
    selected_class = " is-selected" if row.get("selected") == "yes" else ""
    return f"""<article class="market-operation-card is-{escape(row.get("state", "attention"))}{selected_class}">
<span>{escape(row.get("label", "-"))}</span>
<strong>{escape(row.get("disabled_reason", ""))}</strong>
<em>{escape(row.get("caption", ""))}</em>
<small>{escape(row.get("impact", ""))} {escape(row.get("post_action_hint", ""))}</small>
</article>"""


def market_submission_summary_html(summary: dict[str, str]) -> str:
    return f"""<section class="market-submission-summary is-{escape(summary.get("state", "attention"))}" aria-label="資料補強送出前摘要">
<span>送出前摘要</span>
<strong>{escape(summary.get("title", ""))}</strong>
<p>{escape(summary.get("detail", ""))}</p>
<em>{escape(summary.get("next_step", ""))}</em>
<small>{escape(summary.get("quota_hint", ""))}</small>
</section>"""


def market_action_impact_grid_html() -> str:
    return """<div class="action-impact-grid" aria-label="資料補強影響">
<div><strong>刷新股價</strong><span>會更新最新版報告的股價與成交量判讀</span></div>
<div><strong>刷新 5 年財報</strong><span>會補齊五年財務與品質門檻需要的財報資料</span></div>
<div><strong>刷新估值</strong><span>會更新本益比、股價淨值比與殖利率判讀</span></div>
<div><strong>補抓公司文件</strong><span>會補齊公司文件、法說會或公開資訊缺口</span></div>
</div>"""


def market_cache_operator_summary_html(rows: list[dict[str, str]]) -> str:
    cards_html = "\n".join(market_cache_card_html(row) for row in rows)
    return f"""<section class="market-cache-readiness" aria-label="市場快取新鮮度">
<div class="market-cache-readiness-head">
<div class="workspace-kicker">市場快取新鮮度</div>
<h3>先刷新最會影響報告判讀的資料</h3>
<p>股價、估值、財報與公司文件會影響最新版報告的品質門檻與補強建議。</p>
</div>
<div class="market-cache-readiness-list">
{cards_html}
</div>
</section>"""


def market_cache_card_html(row: dict[str, str]) -> str:
    return f"""<article class="market-cache-card is-{escape(row.get("state", "attention"))}">
<span>{escape(row.get("title", "-"))}</span>
<strong>{escape(row.get("value", "-"))}</strong>
<em>{escape(row.get("caption", ""))}</em>
<small>{escape(row.get("action_label", ""))}</small>
</article>"""
