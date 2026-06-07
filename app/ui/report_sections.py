from __future__ import annotations

import re
from html import escape

from app.ui.report_formatters import (
    current_price_badge_class,
    decision_badge_class,
    downside_badge_class,
    valuation_badge_class,
)
from app.ui.report_markdown import (
    markdown_items,
    markdown_section_or_none,
    markdown_table_rows,
    markdown_table_rows_by_header,
)


def detail_html(markdown: str, title: str, heading: str, limit: int = 4) -> str:
    items = markdown_items(markdown, heading, limit=limit)
    if not items:
        return ""
    body = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<details><summary>{escape(title)}</summary><ul>{body}</ul></details>"


def next_steps_html(markdown: str) -> str:
    section = markdown_section_or_none(markdown, "下一步行動")
    if not section:
        return "<p class='muted'>先補資料後再重新分析。</p>"

    groups: list[dict] = []
    current: dict = {"title": "處理原則", "items": []}
    for raw_line in section.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            if current["items"]:
                groups.append(current)
            current = {"title": line.replace("###", "").strip(), "items": []}
            continue
        if line.startswith("|"):
            continue
        text = ""
        if line.startswith("- "):
            text = line[2:].strip()
        elif re.match(r"^\d+\.\s+", line):
            text = re.sub(r"^\d+\.\s+", "", line).strip()
        if text:
            current["items"].append(text)
    if current["items"]:
        groups.append(current)

    if not groups:
        return "<p class='muted'>先補資料後再重新分析。</p>"

    blocks = []
    for group in groups:
        items = group["items"]
        if not isinstance(items, list) or not items:
            continue
        body = "".join(f"<li>{escape(item)}</li>" for item in items)
        blocks.append(
            f"""
            <div class="next-step-group">
              <strong>{escape(str(group["title"]))}（{len(items)} 項）</strong>
              <ul>{body}</ul>
            </div>
            """
        )
    return "".join(blocks) or "<p class='muted'>先補資料後再重新分析。</p>"


def company_analysis_html(markdown: str) -> str:
    section = markdown_section_or_none(markdown, "個別公司分析")
    if not section:
        return ""
    company_blocks = re.split(r"(?m)^### (?=\d{4}\s)", section)
    cards = []
    for block in company_blocks[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        title = lines[0].replace("**", "")
        highlights = []
        for line in lines[1:]:
            if line.startswith("### "):
                break
            if line.startswith("#### ") and len(highlights) >= 4:
                break
            if not line.startswith("- "):
                continue
            text = line[2:].replace("**", "").strip()
            if (
                text.startswith(("產業鏈位置", "市場資料", "月營收"))
                or "財務體質判斷" in text
                or "是否低估或高估" in text
                or "本次操作結論" in text
                or "最終結論" in text
            ):
                highlights.append(text)
            if len(highlights) >= 6:
                break
        if not highlights:
            highlights = [
                line[2:].replace("**", "").strip()
                for line in lines[1:]
                if line.startswith("- ")
            ][:4]
        body = "".join(f"<li>{escape(item)}</li>" for item in highlights)
        cards.append(
            f"""
            <details class="company-detail">
              <summary>{escape(title)}</summary>
              <ul>{body or "<li>目前無足夠數據判斷。</li>"}</ul>
            </details>
            """
        )
    if not cards:
        return ""
    return f"<details open><summary>個別公司分析（{len(cards)} 檔）</summary>{''.join(cards)}</details>"


def comparison_matrix_html(markdown: str) -> str:
    rows = markdown_table_rows(markdown, "個股比較矩陣", limit=60)
    if not rows:
        return ""
    cards = []
    action_count = 0
    watch_count = 0
    risk_count = 0
    for row in rows:
        if len(row) >= 9:
            stock_raw, decision_raw, price_raw, price_label_raw = row[0], row[1], row[2], row[3]
            upside_raw, downside_raw, valuation_raw, confidence_raw = row[4], row[5], row[6], row[7]
            reminder_raw = row[8]
        else:
            stock_raw = row[0] if len(row) > 0 else "-"
            decision_raw = row[1] if len(row) > 1 else "-"
            price_raw = "-"
            price_label_raw = "未標示"
            upside_raw = row[2] if len(row) > 2 else "-"
            downside_raw = row[3] if len(row) > 3 else "-"
            valuation_raw = row[4] if len(row) > 4 else "-"
            confidence_raw = row[5] if len(row) > 5 else "-"
            reminder_raw = row[6] if len(row) > 6 else ""
        stock = escape(stock_raw)
        decision = escape(decision_raw)
        price = escape(price_raw)
        price_label = escape(price_label_raw)
        upside = escape(upside_raw)
        downside = escape(downside_raw)
        valuation = escape(valuation_raw)
        confidence = escape(confidence_raw)
        reminder = escape(reminder_raw)
        decision_class = decision_badge_class(decision_raw)
        valuation_class = valuation_badge_class(valuation_raw)
        downside_class = downside_badge_class(downside_raw)
        price_class = current_price_badge_class(price_label_raw)
        if decision_class == "decision-action":
            action_count += 1
        elif decision_class == "decision-risk":
            risk_count += 1
        else:
            watch_count += 1
        cards.append(
            f"""
            <article class="matrix-card {decision_class}">
              <div class="matrix-top">
                <div>
                  <div class="ticker">{stock}</div>
                  <div class="reason">{reminder}</div>
                </div>
                <span class="decision {decision_class}">{decision}</span>
              </div>
              <div class="mini-grid">
                <div><span>最新可取得收盤價</span><strong>{price}</strong></div>
                <div class="{price_class}"><span>追價風險標籤</span><strong>{price_label}</strong></div>
                <div><span>目前情境升值分</span><strong>{upside}</strong></div>
                <div class="{downside_class}"><span>目前情境降值分</span><strong>{downside}</strong></div>
                <div class="{valuation_class}"><span>目前估值</span><strong>{valuation}</strong></div>
                <div><span>信心</span><strong>{confidence}</strong></div>
              </div>
            </article>
            """
        )
    summary = (
        f"<div class='matrix-summary'>"
        f"<span>共 {len(rows)} 檔</span>"
        f"<span>可研究 {action_count}</span>"
        f"<span>觀察 {watch_count}</span>"
        f"<span>風險 {risk_count}</span>"
        f"</div>"
    )
    return summary + "".join(cards)


def early_potential_radar_html(markdown: str) -> str:
    rows = markdown_table_rows(markdown, "早期潛力雷達", limit=8)
    if not rows:
        return ""
    cards = []
    for row in rows:
        if not row or row[0] in {"目前無足夠數據判斷", "目前無足夠數據判斷。"}:
            continue
        stock = escape(row[0]) if len(row) > 0 else "-"
        score = escape(row[1]) if len(row) > 1 else "-"
        attention_raw = row[2] if len(row) > 2 else "-"
        attention = escape(attention_raw)
        upside = escape(row[3]) if len(row) > 3 else "-"
        downside_raw = row[4] if len(row) > 4 else "-"
        downside = escape(downside_raw)
        reason = escape(row[5]) if len(row) > 5 else ""
        source = escape(row[6]) if len(row) > 6 else ""
        attention_class = (
            "attention-low"
            if any(term in attention_raw for term in ["報導較少", "報導偏少", "低關注"])
            else "attention-known"
        )
        cards.append(
            f"""
            <article class="radar-card {attention_class}">
              <div class="matrix-top">
                <div>
                  <div class="ticker">{stock}</div>
                  <div class="reason">{reason}</div>
                </div>
                <span class="decision {attention_class}">{attention}</span>
              </div>
              <div class="mini-grid">
                <div><span>早期線索分</span><strong>{score}</strong></div>
                <div><span>目前情境升值分</span><strong>{upside}</strong></div>
                <div class="{downside_badge_class(downside_raw)}"><span>目前情境降值分</span><strong>{downside}</strong></div>
              </div>
              <div class="thesis-source">{source or "目前無足夠代表來源。"}</div>
            </article>
            """
        )
    return "".join(cards)


def investment_thesis_html(markdown: str) -> str:
    section = markdown_section_or_none(markdown, "投資理由地圖")
    if not section:
        return ""
    company_blocks = re.split(r"(?m)^### (?=\d{4}\s)", section)
    cards = []
    for block in company_blocks[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        title = lines[0].replace("**", "")
        facts = {}
        for line in lines[1:]:
            if not line.startswith("- "):
                continue
            text = line[2:].replace("**", "").strip()
            if "：" not in text:
                continue
            key, value = text.split("：", 1)
            facts[key.strip()] = value.strip()
        source_text = facts.get("代表性來源", "目前無足夠公司層級來源。")
        if facts.get("風險來源"):
            source_text = f"{source_text}｜風險來源：{facts['風險來源']}"
        cards.append(
            f"""
            <article class="thesis-card">
              <div class="thesis-head">
                <div>
                  <div class="ticker">{escape(title)}</div>
                  <div class="reason">{escape(facts.get("目前判斷", "先看資料品質，再決定是否研究。"))}</div>
                </div>
              </div>
              <div class="thesis-body">
                <div><span>值得研究的理由</span><p>{escape(facts.get("具體投資理由", "目前投資理由尚未完整。"))}</p></div>
                <div><span>成長假設</span><p>{escape(facts.get("成長假設", "目前無足夠數據判斷。"))}</p></div>
                <div><span>主要風險</span><p>{escape(facts.get("主要風險", "目前無足夠數據判斷。"))}</p></div>
                {"<div><span>營收口徑提醒</span><p>" + escape(facts.get("營收口徑提醒", "")) + "</p></div>" if facts.get("營收口徑提醒") else ""}
                <div><span>需要再確認</span><p>{escape(facts.get("需要再確認", "等待下一批資料確認。"))}</p></div>
              </div>
              <div class="thesis-source">{escape(source_text)}</div>
            </article>
            """
        )
    return "".join(cards)


def credibility_badge_class(value: str) -> str:
    if any(term in value for term in ["高", "可追溯", "多來源", "可用", "可檢查", "可判讀"]):
        return "credibility-good"
    if any(term in value for term in ["中", "偏少", "需", "觀察"]):
        return "credibility-caution"
    if any(term in value for term in ["低", "不足", "缺"]):
        return "credibility-risk"
    return "credibility-neutral"


def credibility_html(markdown: str) -> str:
    overview_rows = markdown_table_rows_by_header(markdown, "可信度檢查", "檢查項目", limit=8)
    company_rows = markdown_table_rows_by_header(markdown, "可信度檢查", "股票", limit=20)
    rules = markdown_items(markdown, "可信度檢查", limit=5)
    if not overview_rows and not company_rows and not rules:
        return ""
    overview_cards = []
    for row in overview_rows:
        item = escape(row[0]) if len(row) > 0 else "-"
        status_raw = row[1] if len(row) > 1 else "-"
        status = escape(status_raw)
        evidence = escape(row[2]) if len(row) > 2 else "-"
        impact = escape(row[3]) if len(row) > 3 else ""
        overview_cards.append(
            f"""
            <article class="credibility-card">
              <div class="credibility-head">
                <strong>{item}</strong>
                <span class="credibility-badge {credibility_badge_class(status_raw)}">{status}</span>
              </div>
              <p>{evidence}</p>
              <small>{impact}</small>
            </article>
            """
        )
    company_cards = []
    for row in company_rows:
        stock = escape(row[0]) if len(row) > 0 else "-"
        status_raw = row[1] if len(row) > 1 else "-"
        status = escape(status_raw)
        documents = escape(row[2]) if len(row) > 2 else "-"
        findings = escape(row[3]) if len(row) > 3 else "-"
        latest = escape(row[4]) if len(row) > 4 else "-"
        limits = escape(row[5]) if len(row) > 5 else ""
        company_cards.append(
            f"""
            <article class="credibility-company {credibility_badge_class(status_raw)}">
              <div class="credibility-head">
                <strong>{stock}</strong>
                <span class="credibility-badge {credibility_badge_class(status_raw)}">{status}</span>
              </div>
              <div class="mini-grid">
                <div><span>公司文本</span><strong>{documents}</strong></div>
                <div><span>歸因證據</span><strong>{findings}</strong></div>
                <div><span>最近來源</span><strong>{latest}</strong></div>
              </div>
              <small>{limits}</small>
            </article>
            """
        )
    rules_html = "".join(f"<li>{escape(rule)}</li>" for rule in rules)
    return (
        "<div class='credibility-grid'>"
        + "".join(overview_cards)
        + "</div>"
        + ("<h3>個股可信度核對</h3><div class='credibility-companies'>" + "".join(company_cards) + "</div>" if company_cards else "")
        + ("<details><summary>可信度判讀規則</summary><ul>" + rules_html + "</ul></details>" if rules_html else "")
    )


def follow_up_tasks_html(markdown: str) -> str:
    rows = markdown_table_rows(markdown, "自動補強任務", limit=8)
    if not rows:
        return ""
    cards = []
    for row in rows:
        task = escape(row[0]) if len(row) > 0 else "-"
        tickers = escape(row[1]) if len(row) > 1 else "-"
        purpose = escape(row[2]) if len(row) > 5 else "追蹤更新"
        priority = escape(row[3]) if len(row) > 5 else escape(row[2]) if len(row) > 2 else "-"
        frequency = escape(row[4]) if len(row) > 5 else escape(row[3]) if len(row) > 3 else "-"
        reason = escape(row[5]) if len(row) > 5 else escape(row[4]) if len(row) > 4 else ""
        cards.append(
            f"""
            <article class="task-card">
              <div>
                <div class="ticker">{task}</div>
                <div class="reason">{reason}</div>
              </div>
              <div class="task-meta">
                <span>{tickers}</span>
                <span>{purpose}</span>
                <span>{priority}</span>
                <span>{frequency}</span>
              </div>
            </article>
            """
        )
    return "".join(cards)
