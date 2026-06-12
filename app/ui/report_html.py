from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Optional
from collections.abc import Callable

READING_BUDGET_PREVIEW_LIMIT = 3

from app.ui.report_candidate_audit import candidate_audit_html
from app.ui.report_formatters import (
    auto_follow_up_status_html,
    confidence_label,
    current_price_badge_class,
    metric_count_from_payload,
    metric_int,
    metric_percent,
    plan_quality_label,
    quality_issue_html,
)
from app.ui.report_markdown import (
    first_tranche_allocation_label,
    markdown_items,
    markdown_table_rows,
    summary_table_items,
)
from app.ui.report_sections import (
    company_analysis_html,
    comparison_matrix_cards,
    credibility_html,
    detail_html,
    early_potential_radar_cards,
    follow_up_task_cards,
    investment_thesis_cards,
    next_steps_html,
)

REPORT_HTML_STYLE_PATH = Path(__file__).with_name("styles") / "report_html.css"


def load_report_html_css() -> str:
    return REPORT_HTML_STYLE_PATH.read_text(encoding="utf-8")


def reading_budget_section_html(
    *,
    section_id: str,
    title: str,
    noun: str,
    items: list[str],
    summary_html: str = "",
    preview_limit: int = READING_BUDGET_PREVIEW_LIMIT,
    preview_items: list[str] | None = None,
    empty_html: str = "<p class='muted'>目前沒有可呈現的資料。</p>",
    list_class: str = "",
) -> str:
    total = len(items)
    selected_preview = preview_items if preview_items is not None else items[:preview_limit]
    visible_count = min(len(selected_preview), total)
    title_with_count = f"{title}（{total} {noun}）" if total else title
    if total == 0:
        return f"<section class='panel' data-reading-budget='{escape(section_id)}'><h2>{escape(title)}</h2>{empty_html}</section>"

    preview_body = "".join(selected_preview) or empty_html
    preview_class = f"reading-budget-preview {list_class}".strip()
    if total <= preview_limit:
        return f"""
        <section class="panel reading-budget-section" data-reading-budget="{escape(section_id)}">
          <div class="reading-budget-head">
            <h2>{escape(title_with_count)}</h2>
            <span>顯示 {visible_count} / {total}</span>
          </div>
          {summary_html}
          <div class="{escape(preview_class)}" data-reading-budget-preview="{escape(section_id)}">{preview_body}</div>
        </section>
        """

    remaining = total - visible_count
    full_class = f"reading-budget-full {list_class}".strip()
    return f"""
    <section class="panel reading-budget-section" data-reading-budget="{escape(section_id)}">
      <div class="reading-budget-head">
        <h2>{escape(title_with_count)}</h2>
        <span>顯示 {visible_count} / {total}</span>
      </div>
      {summary_html}
      <div class="{escape(preview_class)}" data-reading-budget-preview="{escape(section_id)}">{preview_body}</div>
      <p class="reading-budget-more">另有 {remaining} {noun}可展開</p>
      <details class="reading-budget-details">
        <summary>展開全部 {total} {noun}</summary>
        <div class="{escape(full_class)}" data-reading-budget-full="{escape(section_id)}">{"".join(items)}</div>
      </details>
    </section>
    """


def investment_advice_cards(markdown: str) -> list[str]:
    investment_rows = markdown_table_rows(markdown, "投資建議", limit=60)
    cards = []
    for row in investment_rows:
        if len(row) >= 7:
            ticker_raw, price_raw, price_label_raw, decision_raw, reason_raw = row[0], row[1], row[2], row[3], row[4]
        else:
            ticker_raw = row[0] if len(row) > 0 else "-"
            price_raw = "-"
            price_label_raw = "未標示"
            decision_raw = row[1] if len(row) > 1 else "-"
            reason_raw = row[2] if len(row) > 2 else ""
        ticker = escape(ticker_raw)
        price = escape(price_raw)
        price_label = escape(price_label_raw)
        decision = escape(decision_raw)
        reason = escape(reason_raw)
        price_class = current_price_badge_class(price_label_raw)
        cards.append(
            f"""
            <article class="stock-card">
              <div>
                <div class="ticker">{ticker}</div>
                <div class="stock-meta">
                  <span>{price}</span>
                  <strong class="{price_class}">{price_label}</strong>
                </div>
                <div class="reason">{reason}</div>
              </div>
              <span class="decision">{decision}</span>
            </article>
            """
        )
    return cards


def report_html(markdown: str, result: Optional[dict] = None) -> str:
    gate = result.get("quality_gate") if result else None
    gate = gate if isinstance(gate, dict) else {}
    metrics = gate.get("metrics") or {}
    action_policy = gate.get("action_policy") or {}
    status = gate.get("status", "unknown")
    status_labels = {
        "ready": "資料品質可用",
        "caution": "需謹慎判讀",
        "insufficient": "資料不足",
        "unknown": "未標示",
    }
    status_class = status if status in {"ready", "caution", "insufficient"} else "unknown"
    quality_html = quality_issue_html(gate)
    amount = action_policy.get("max_deployable_amount")
    amount_label = f"{int(amount):,} 元" if amount is not None else "-"
    current_allocation_label = first_tranche_allocation_label(markdown) or amount_label
    report_id = result.get("report_id") if result else "-"
    request_payload = result.get("request") if result else {}
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    current_topic = (result or {}).get("topic") or request_payload.get("topic")
    current_tickers = (result or {}).get("tickers") or (result or {}).get("promoted_tickers") or request_payload.get("tickers") or []
    auto_html = auto_follow_up_status_html(
        result.get("auto_follow_up") if result else None,
        report_id,
        current_topic,
        current_tickers,
    )
    lookback_days = request_payload.get("lookback_days") or metrics.get("source_lookback_days")
    recent_source_label = f"近 {int(lookback_days)} 天來源" if lookback_days else "近況來源"
    promoted = metric_count_from_payload(result, "promoted_tickers", metrics, "promoted_count")
    candidate_count = len(result.get("candidate_whitelist", [])) if result else "-"
    source_count = metrics.get("dynamic_source_count", 0)
    publisher_count = metric_int(metrics.get("source_unique_publishers"))
    timestamp_coverage = metric_percent(metrics.get("source_timestamp_coverage"))
    recent_coverage = metric_percent(metrics.get("source_recent_coverage"))
    leading_signal_coverage = metric_percent(metrics.get("leading_signal_coverage"))
    confidence_min = confidence_label(metrics.get("formal_confidence_min"))
    discovery_plan_quality = plan_quality_label(metrics)

    summary_items = summary_table_items(markdown) + markdown_items(markdown, "一頁摘要", limit=3)
    time_scope_items = markdown_items(markdown, "時間口徑說明", limit=5)
    criteria_items = markdown_items(markdown, "判斷準則說明", limit=5)
    guard_items = markdown_items(markdown, "投資行動限制", limit=3)
    investment_cards = investment_advice_cards(markdown)
    early_radar_cards = early_potential_radar_cards(markdown)
    comparison_summary_html, comparison_cards = comparison_matrix_cards(markdown)
    thesis_cards = investment_thesis_cards(markdown)
    credibility_panel = credibility_html(markdown)
    follow_up_cards = follow_up_task_cards(markdown)
    audit_html = candidate_audit_html(markdown, result)
    final_items = markdown_items(markdown, "二次綜合篩選", limit=3)

    summary_html = "".join(f"<li>{escape(item)}</li>" for item in summary_items) or "<li>目前無足夠數據判斷。</li>"
    time_scope_html = "".join(f"<li>{escape(item)}</li>" for item in time_scope_items)
    criteria_html = "".join(f"<li>{escape(item)}</li>" for item in criteria_items)
    action_html = next_steps_html(markdown)
    guard_html = "".join(f"<li>{escape(item)}</li>" for item in guard_items)
    final_html = "".join(f"<li>{escape(item)}</li>" for item in final_items)
    details = "".join(
        [
            detail_html(markdown, "資金控管", "資金控管建議", limit=24),
            company_analysis_html(markdown),
            detail_html(markdown, "主要風險", "主要風險與瓶頸"),
            detail_html(markdown, "資料完整度", "資料完整度"),
            detail_html(markdown, "來源覆蓋", "來源覆蓋"),
            detail_html(markdown, "評分明細", "評分明細"),
            detail_html(markdown, "時間口徑", "時間口徑說明"),
            detail_html(markdown, "判斷準則", "判斷準則說明"),
        ]
    )
    report_css = load_report_html_css()
    return f"""
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{report_css}</style>
</head>
<body>
<main class="report">
  <section class="hero">
    <div class="kicker">AI 台股分析報告</div>
    <h1>先看能不能用，再看要不要研究</h1>
    <span class="status {status_class}">{escape(status_labels.get(status, status))}</span>
    <p class="muted">{escape(action_policy.get("label", "請先檢查資料品質與來源覆蓋。"))}</p>
    <p class="muted">本頁的「目前情境升值分」與「目前情境降值分」是依已取得資料計算的研究排序分數，不是未來報酬率、目標價或買賣指令。</p>
    <div class="grid">
      <div class="metric"><span>報告</span><strong>#{escape(str(report_id))}</strong></div>
      <div class="metric"><span>本次配置</span><strong>{escape(current_allocation_label)}</strong></div>
      <div class="metric"><span>正式分析股票</span><strong>{escape(str(promoted))}</strong></div>
      <div class="metric"><span>候選清單</span><strong>{escape(str(candidate_count))}</strong></div>
    </div>
    <div class="trust-grid">
      <div class="metric"><span>來源篇數</span><strong>{escape(str(source_count))}</strong></div>
      <div class="metric"><span>來源家數</span><strong>{escape(publisher_count)}</strong></div>
      <div class="metric"><span>來源有日期</span><strong>{escape(timestamp_coverage)}</strong></div>
      <div class="metric"><span>{escape(recent_source_label)}</span><strong>{escape(recent_coverage)}</strong></div>
      <div class="metric"><span>近況訊號覆蓋</span><strong>{escape(leading_signal_coverage)}</strong></div>
      <div class="metric"><span>最低信心</span><strong>{escape(confidence_min)}</strong></div>
      <div class="metric"><span>拆解任務品質</span><strong>{escape(discovery_plan_quality)}</strong></div>
    </div>
  </section>
  {auto_html}
  <section class="decision-rail" aria-label="閱讀提示">
      <div class="rail-block"><strong>閱讀順序</strong><p>先看本次配置與可研究檔數，再看避開名單，最後展開查核來源。</p></div>
      <div class="rail-block"><strong>投資口徑</strong><p>正式分析只代表資料通過門檻，不等於買進名單；所有分數只用於排序與風險控管。</p></div>
      <div class="rail-block"><strong>時間口徑</strong><p>「目前」代表本報告生成前已取得的資料；「情境」代表假設分數，不是未來保證。</p></div>
      <div class="rail-block"><strong>補強狀態</strong><p>若有必要缺口，系統會啟動補資料任務，完成後才重跑報告。</p></div>
  </section>
  <div class="report-grid">
    <div class="report-main">
      {quality_html}
      <section class="panel"><h2>重點摘要</h2><ul>{summary_html}</ul></section>
      {"<section class='panel'><h2>可信度檢查</h2>" + credibility_panel + "</section>" if credibility_panel else ""}
      {"<section class='panel'><h2>時間口徑</h2><ul>" + time_scope_html + "</ul></section>" if time_scope_html else ""}
      {"<section class='panel'><h2>判斷準則</h2><ul>" + criteria_html + "</ul></section>" if criteria_html else ""}
      {"<section class='panel'><h2>投資行動限制</h2><ul>" + guard_html + "</ul></section>" if guard_html else ""}
      <section class="panel"><h2>下一步</h2>{action_html}</section>
      {"<section class='panel'><h2>候選公司審計</h2>" + audit_html + "</section>" if audit_html else ""}
      {reading_budget_section_html(
          section_id="follow-up-tasks",
          title="系統會自動補強",
          noun="項",
          items=follow_up_cards,
          list_class="stock-list",
      ) if follow_up_cards else ""}
      {reading_budget_section_html(
          section_id="early-potential-radar",
          title="早期潛力雷達",
          noun="檔",
          items=early_radar_cards,
          summary_html="<p class='muted'>專看截至目前報導較少、但近況訊號轉強的研究線索；不是買賣指令，也不是自選股狀態。</p>",
          list_class="matrix-list",
      ) if early_radar_cards else ""}
      {reading_budget_section_html(
          section_id="comparison-matrix",
          title="個股比較矩陣",
          noun="檔",
          items=comparison_cards,
          summary_html=comparison_summary_html,
          list_class="matrix-list",
      ) if comparison_cards else ""}
      {reading_budget_section_html(
          section_id="investment-thesis",
          title="投資理由地圖",
          noun="張",
          items=thesis_cards,
          list_class="thesis-list",
      ) if thesis_cards else ""}
      {reading_budget_section_html(
          section_id="investment-advice",
          title="個股建議",
          noun="檔",
          items=investment_cards,
          empty_html="<p class='muted'>目前沒有可呈現的個股建議。</p>",
          list_class="stock-list",
      )}
      {"<section class='panel'><h2>二次篩選</h2><ul>" + final_html + "</ul></section>" if final_html else ""}
      <section class="panel"><h2>展開看細節</h2>{details or "<p class='muted'>目前沒有更多細節。</p>"}</section>
    </div>
  </div>
</main>
</body>
</html>
"""
