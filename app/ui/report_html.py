from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Optional

from app.services.candidate_confidence import format_confidence_score
from app.ui.report_candidate_audit import candidate_audit_html
from app.ui.report_markdown import (
    first_tranche_allocation_label,
    markdown_items,
    markdown_section_or_none,
    markdown_table_rows,
    markdown_table_rows_by_header,
    summary_table_items,
)

REPORT_HTML_STYLE_PATH = Path(__file__).with_name("styles") / "report_html.css"


def load_report_html_css() -> str:
    return REPORT_HTML_STYLE_PATH.read_text(encoding="utf-8")


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


def decision_badge_class(value: str) -> str:
    if "可小額" in value or "可研究" in value:
        return "decision-action"
    if "避開" in value or "降低曝險" in value:
        return "decision-risk"
    return "decision-watch"


def valuation_badge_class(value: str) -> str:
    if "偏高" in value or "略高" in value:
        return "valuation-high"
    if "低於" in value or "略低" in value:
        return "valuation-low"
    return "valuation-neutral"


def current_price_badge_class(value: str) -> str:
    if "可小額" in value or "可研究" in value:
        return "price-action"
    if "不適合" in value or "等止跌" in value or "風險" in value:
        return "price-risk"
    if "等回檔" in value or "觀察" in value or "勿追高" in value:
        return "price-watch"
    return "price-neutral"


def downside_badge_class(value: str) -> str:
    digits = re.sub(r"[^\d.]", "", value)
    if not digits:
        return ""
    return "risk-high" if float(digits) > 5 else "risk-low"


def quality_issue_html(gate: dict) -> str:
    blockers = gate.get("blockers") or []
    warnings = gate.get("warnings") or []
    observations = gate.get("observations") or []
    actions = gate.get("remediation_actions") or []
    if not blockers and not warnings and not observations and not actions:
        return ""
    items = []
    for blocker in blockers:
        items.append(f"<li><strong>阻擋：</strong>{escape(investor_friendly_quality_text(blocker))}</li>")
    for warning in warnings:
        items.append(f"<li><strong>警示：</strong>{escape(investor_friendly_quality_text(warning))}</li>")
    for observation in observations:
        items.append(f"<li><strong>觀察：</strong>{escape(investor_friendly_quality_text(observation))}</li>")
    action_items = "".join(f"<li>{escape(investor_friendly_quality_text(action))}</li>" for action in actions)
    action_html = (
        "<div class='quality-actions'><strong>建議補強</strong><ul>" + action_items + "</ul></div>"
        if action_items
        else ""
    )
    issue_html = "<ul>" + "".join(items) + "</ul>" if items else ""
    if blockers:
        title = "品質阻擋"
        severity_class = "quality-blockers"
    elif warnings:
        title = "品質警示"
        severity_class = "quality-warnings"
    elif actions:
        title = "建議補強"
        severity_class = "quality-actions-only"
    else:
        title = "品質觀察"
        severity_class = "quality-observations"
    return f"<section class='panel quality-issues {severity_class}'><h2>{title}</h2>{issue_html}{action_html}</section>"


def auto_follow_up_status_html(
    auto_follow_up: Optional[dict],
    current_report_id: object = None,
    current_topic: object = None,
    current_tickers: Optional[list] = None,
) -> str:
    if not isinstance(auto_follow_up, dict) or not auto_follow_up:
        return ""
    status = auto_follow_up.get("status")
    if status in {None, "not_needed", "disabled"}:
        return ""
    summary = auto_follow_up.get("summary") or {}
    selected = summary.get("selected") or {}
    execution = summary.get("execution") or {}
    rerun_raw = auto_follow_up.get("rerun_report")
    rerun = rerun_raw if isinstance(rerun_raw, dict) else {}
    next_report = rerun.get("report_id")
    source_report_id = auto_follow_up.get("source_report_id")
    source_topic = auto_follow_up.get("source_report_topic")
    source_tickers = auto_follow_up.get("source_report_tickers") or []
    rerun_request = rerun.get("request") if isinstance(rerun.get("request"), dict) else {}
    rerun_topic = rerun_request.get("topic") or rerun.get("topic")
    next_report_is_newer = bool(next_report and current_report_id and str(next_report) != str(current_report_id))
    if source_report_id and current_report_id and str(source_report_id) != str(current_report_id):
        return ""
    if next_report_is_newer and not source_topic:
        return ""
    if current_topic and source_topic and str(current_topic) != str(source_topic):
        return ""
    if current_topic and rerun_topic and str(current_topic) != str(rerun_topic):
        return ""
    if source_topic and rerun_topic and str(source_topic) != str(rerun_topic):
        return ""
    if next_report_is_newer and not rerun_topic:
        return ""
    if current_tickers and isinstance(source_tickers, list) and source_tickers:
        if [str(ticker) for ticker in source_tickers] != [str(ticker) for ticker in current_tickers]:
            return ""
    if next_report_is_newer and not source_tickers:
        return ""
    skipped_reason = rerun.get("reason")
    if status == "failed":
        title = "自動補強未完成"
        body = escape(str(auto_follow_up.get("reason") or "補強流程執行失敗，請稍後重試。"))
        tone = "auto-failed"
    elif status == "unavailable":
        title = "自動補強暫時無法啟動"
        body = escape(str(auto_follow_up.get("reason") or "後端補強服務暫時無法連線。"))
        tone = "auto-paused"
    elif status == "running":
        title = "自動補強執行中"
        body = (
            f"系統正在處理 {len(auto_follow_up.get('planned_actions') or [])} 項補強任務；"
            "完成後會更新補強紀錄，必要時產生新版報告。"
        )
        tone = "auto-started"
    elif status == "queued":
        title = "已排入自動補強"
        body = (
            f"系統已偵測到必要資料缺口，排入 {int(selected.get('required_count') or selected.get('total_count') or 0)} "
            "項補強任務；完成後會依完成檢查決定是否重跑報告。"
        )
        tone = "auto-started"
    elif next_report_is_newer:
        if not source_report_id or str(source_report_id) != str(current_report_id):
            return ""
        title = "已有新版報告可查看"
        body = (
            f"目前畫面是報告 #{escape(str(current_report_id))}；"
            f"自動補強已另產生新版報告 #{escape(str(next_report))}。"
            "請切換到新版檢視補強後結論，避免把舊版內容誤認為已更新。"
        )
        tone = "auto-paused"
    elif next_report:
        title = "已自動補強並產生新版報告"
        body = (
            f"系統偵測到資料缺口後已啟動 {int(selected.get('total_count') or 0)} 項補強，"
            f"補入/更新 {int(execution.get('stored_count') or 0)} 筆資料，並產生報告 #{escape(str(next_report))}。"
        )
        tone = "auto-started"
    elif skipped_reason:
        title = "已自動補強，重跑暫停"
        body = escape(str(skipped_reason))
        tone = "auto-paused"
    else:
        title = "已自動啟動補強"
        body = (
            f"系統偵測到資料缺口後已啟動 {int(selected.get('total_count') or 0)} 項補強，"
            f"補入/更新 {int(execution.get('stored_count') or 0)} 筆資料。"
        )
        tone = "auto-started"
    return f"""
    <section class="auto-follow-up {tone}">
      <div>
        <strong>{escape(title)}</strong>
        <p>{body}</p>
      </div>
    </section>
    """


def investor_friendly_quality_text(item: object) -> str:
    text = str(item)
    replacements = {
        "LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿": (
            "模型補充分析未啟用或呼叫失敗，個股結論主要由資料規則產生，需人工覆核"
        ),
        "LLM 補充分析已完成，且仍受來源與白名單驗證約束": (
            "模型補充分析已完成，仍只採用可追溯來源與白名單公司"
        ),
        "AI 動態資料來源": "自動搜尋資料來源",
        "AI 拆解": "主題拆解",
        "LLM 補充分析": "模型補充分析",
        "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。": (
            "請系統管理者恢復模型補充分析，恢復後重新產生報告並保留事實核查。"
        ),
        "LLM API key": "模型連線設定",
        "官方 IR 文件": "官方投資人關係文件",
        "規則引擎草稿": "資料規則草稿",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def metric_percent(value: object) -> str:
    return "未評估" if value is None else f"{float(value or 0):.0%}"


def metric_int(value: object) -> str:
    return "未評估" if value is None else str(value)


def metric_number(value: object) -> str:
    if value is None:
        return "未評估"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def metric_count_from_payload(
    result: Optional[dict],
    list_key: str,
    metrics: dict,
    metric_key: str,
    default: object = "-",
) -> object:
    if result and list_key in result and isinstance(result.get(list_key), list):
        return len(result.get(list_key) or [])
    value = metrics.get(metric_key)
    return value if value is not None else default


def confidence_label(value: object) -> str:
    return format_confidence_score(float(value)) if value is not None else "未匯入"


def plan_quality_label(metrics: dict) -> str:
    status = metrics.get("discovery_plan_status")
    score = metrics.get("discovery_plan_score")
    if status is None and score is None:
        return "未評估"
    labels = {
        "ready": "完整",
        "caution": "可用",
        "insufficient": "不足",
        "unknown": "未評估",
    }
    label = labels.get(str(status or "unknown"), str(status or "未評估"))
    if score is None:
        return label
    return f"{label}（{int(float(score))} 分）"


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
    investment_rows = markdown_table_rows(markdown, "投資建議", limit=20)
    early_radar_html = early_potential_radar_html(markdown)
    comparison_html = comparison_matrix_html(markdown)
    thesis_html = investment_thesis_html(markdown)
    credibility_panel = credibility_html(markdown)
    follow_up_html = follow_up_tasks_html(markdown)
    audit_html = candidate_audit_html(markdown, result)
    final_items = markdown_items(markdown, "二次綜合篩選", limit=3)

    summary_html = "".join(f"<li>{escape(item)}</li>" for item in summary_items) or "<li>目前無足夠數據判斷。</li>"
    time_scope_html = "".join(f"<li>{escape(item)}</li>" for item in time_scope_items)
    criteria_html = "".join(f"<li>{escape(item)}</li>" for item in criteria_items)
    action_html = next_steps_html(markdown)
    guard_html = "".join(f"<li>{escape(item)}</li>" for item in guard_items)
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
    investment_html = "".join(cards) or "<p class='muted'>目前沒有可呈現的個股建議。</p>"
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
      {"<section class='panel'><h2>系統會自動補強</h2>" + follow_up_html + "</section>" if follow_up_html else ""}
      {"<section class='panel'><h2>早期潛力雷達</h2><p class='muted'>專看截至目前報導較少、但近況訊號轉強的研究線索；不是買賣指令，也不是自選股狀態。</p><div class='matrix-list'>" + early_radar_html + "</div></section>" if early_radar_html else ""}
      {"<section class='panel'><h2>個股比較矩陣</h2><div class='matrix-list'>" + comparison_html + "</div></section>" if comparison_html else ""}
      {"<section class='panel'><h2>投資理由地圖</h2><div class='thesis-list'>" + thesis_html + "</div></section>" if thesis_html else ""}
      <section class="panel"><h2>個股建議</h2><div class="stock-list">{investment_html}</div></section>
      {"<section class='panel'><h2>二次篩選</h2><ul>" + final_html + "</ul></section>" if final_html else ""}
      <section class="panel"><h2>展開看細節</h2>{details or "<p class='muted'>目前沒有更多細節。</p>"}</section>
    </div>
  </div>
</main>
</body>
</html>
"""
