from __future__ import annotations

# ruff: noqa: F401
import json
import re
from datetime import datetime, time, timedelta
from html import escape
from pathlib import Path
from typing import Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

from app.core.config import get_settings
from app.core.time import today_taipei
from app.services.entity_mapping import EntityMapper
from app.services.report_quality import (
    parse_quality_gate_from_markdown,
)
from app.services.candidate_confidence import format_confidence_score
from app.services.source_quality import is_low_quality_investor_forum_source, remove_low_quality_investor_forum_lines
from app.services.whitelist import SupplyChainWhitelist

STYLE_PATH = Path(__file__).with_name("styles") / "stock_dashboard.css"


def load_dashboard_css() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def configure_page(page_title: str = "台股 AI 產業鏈分析") -> None:
    st.set_page_config(page_title=page_title, layout="wide")
    load_dashboard_css()


API_BASE_URL = get_settings().api_base_url.rstrip("/")
API_GET_TIMEOUT_SECONDS = 10
API_WRITE_TIMEOUT_SECONDS = 60
API_TASK_QUEUE_TIMEOUT_SECONDS = 20


def api_post(path: str, payload: dict, *, timeout: float = API_WRITE_TIMEOUT_SECONDS) -> dict:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def api_task_post(path: str, payload: dict) -> dict:
    return api_post(path, payload, timeout=API_TASK_QUEUE_TIMEOUT_SECONDS)


def api_put(path: str, payload: dict) -> dict:
    response = requests.put(f"{API_BASE_URL}{path}", json=payload, timeout=API_WRITE_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def api_delete(path: str) -> dict:
    response = requests.delete(f"{API_BASE_URL}{path}", timeout=API_WRITE_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def api_get(path: str):
    response = requests.get(f"{API_BASE_URL}{path}", timeout=API_GET_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def request_error_message(exc: requests.RequestException) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)
    try:
        payload = response.json()
    except ValueError:
        return str(exc)
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("code") or exc)
        next_steps = [str(step) for step in detail.get("next_steps") or [] if str(step).strip()]
        if next_steps:
            return f"{message} 建議：" + "；".join(next_steps)
        return message
    if isinstance(detail, str) and detail:
        return detail
    return str(exc)


def queue_data_operation(operation: str, payload: dict) -> dict:
    return api_task_post(
        "/tasks/data-operation",
        {
            "operation": operation,
            "payload": payload,
        },
    )


def task_payload_dates(start_date, end_date) -> dict:
    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }


def hydrate_active_report_result(result: dict) -> dict:
    source_report_id = result.get("report_id")
    active_report_id = result.get("active_report_id") or source_report_id
    if active_report_id:
        payload = report_payload_or_none(active_report_id)
        if payload and report_topics_match(result, payload):
            return hydrate_report_result_from_payload(result, payload, source_report_id)

    latest_payload = latest_report_payload_for_topic(result)
    if latest_payload:
        return hydrate_report_result_from_payload(result, latest_payload, source_report_id)
    return result


def report_payload_or_none(report_id) -> dict | None:
    try:
        payload = api_get(f"/reports/{int(report_id)}")
    except (TypeError, ValueError, requests.RequestException):
        return None
    return payload if isinstance(payload, dict) else None


def latest_report_payload_for_topic(result: dict) -> dict | None:
    current_topic = result_topic(result)
    if not current_topic:
        return None
    try:
        reports = api_get("/reports?limit=50")
    except requests.RequestException:
        return None
    if not isinstance(reports, list):
        return None
    for report in reports:
        if not isinstance(report, dict):
            continue
        if str(report.get("topic") or "").strip() != current_topic:
            continue
        return report_payload_or_none(report.get("id"))
    return None


def result_topic(result: dict) -> str:
    return str(result.get("topic") or (result.get("request") or {}).get("topic") or "").strip()


def report_topics_match(result: dict, payload: dict) -> bool:
    current_topic = result_topic(result)
    active_topic = str(payload.get("topic") or (payload.get("request") or {}).get("topic") or "").strip()
    return not (current_topic and active_topic and current_topic != active_topic)


def hydrate_report_result_from_payload(result: dict, payload: dict, source_report_id) -> dict:
    report_id = payload.get("id") or payload.get("report_id") or source_report_id
    hydrated = {
        **result,
        "report_id": report_id,
        "source_report_id": source_report_id,
        "topic": payload.get("topic") or result.get("topic"),
        "tickers": payload.get("tickers") or result.get("promoted_tickers") or [],
        "request": payload.get("request") or result.get("request") or {},
        "quality_gate": payload.get("quality_gate") or parse_quality_gate_from_markdown(payload.get("markdown") or ""),
        "auto_follow_up": payload.get("auto_follow_up"),
        "candidate_whitelist": payload.get("candidate_whitelist") or result.get("candidate_whitelist") or [],
        "candidate_audit": payload.get("candidate_audit") or result.get("candidate_audit") or {},
        "report": {
            **(result.get("report") or {}),
            "title": payload.get("title") or (result.get("report") or {}).get("title"),
            "markdown": payload.get("markdown") or (result.get("report") or {}).get("markdown"),
        },
    }
    return hydrated


def parse_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def render_section_header(title: str, note: str = "") -> None:
    note_html = f'<div class="section-note">{escape(note)}</div>' if note else ""
    st.markdown(
        f"""
        <div class="section-head">
            <div>
                <div class="section-title">{escape(title)}</div>
                {note_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def markdown_section(markdown: str, heading: str) -> str:
    marker = f"## {heading}"
    start = markdown.find(marker)
    if start == -1:
        return "目前無足夠數據判斷。"
    next_heading = markdown.find("\n## ", start + len(marker))
    return markdown[start:next_heading].strip() if next_heading != -1 else markdown[start:].strip()


def markdown_section_or_none(markdown: str, heading: str) -> Optional[str]:
    section = markdown_section(markdown, heading)
    return None if section == "目前無足夠數據判斷。" else section


def render_report_block(title: str, markdown: str, heading: str, expanded: bool = False) -> None:
    section = markdown_section_or_none(markdown, heading)
    if not section:
        return
    with st.expander(title, expanded=expanded):
        st.markdown(section)


def markdown_items(markdown: str, heading: str, limit: int = 5) -> list[str]:
    section = markdown_section_or_none(markdown, heading)
    if not section:
        return []
    rows = []
    for raw_line in section.splitlines()[1:]:
        line = raw_line.strip()
        if not line or line.startswith("|---"):
            continue
        if line.startswith("|"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        elif re.match(r"^\d+\.\s+", line):
            line = re.sub(r"^\d+\.\s+", "", line).strip()
        line = line.replace("**", "").replace("###", "").replace("##", "").strip()
        if line:
            rows.append(line)
        if len(rows) >= limit:
            break
    return rows


def markdown_table_rows(markdown: str, heading: str, limit: int = 6) -> list[list[str]]:
    section = markdown_section_or_none(markdown, heading)
    if not section:
        return []
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"股票", "項目", "任務"}:
            continue
        rows.append(cells)
        if len(rows) >= limit:
            break
    return rows


def summary_table_items(markdown: str) -> list[str]:
    rows = markdown_table_rows(markdown, "一頁摘要", limit=10)
    important = {"可小額研究", "觀察/待補", "避開/降低曝險", "本次股票範圍"}
    return [f"{row[0]}：{row[1]}" for row in rows if len(row) >= 2 and row[0] in important]


def first_tranche_allocation_label(markdown: str) -> Optional[str]:
    section = markdown_section_or_none(markdown, "資金控管建議")
    if not section or "目前無可配置標的" in section:
        return "0 元"
    match = re.search(r"本輪首筆配置合計約\s*([\d,]+)\s*元", section)
    if not match:
        return None
    return f"{match.group(1)} 元"


def markdown_table_rows_by_header(
    markdown: str,
    heading: str,
    required_first_header: str,
    limit: int = 20,
) -> list[list[str]]:
    section = markdown_section_or_none(markdown, heading)
    if not section:
        return []
    rows = []
    in_target_table = False
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if in_target_table and rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells:
            continue
        if cells[0] == required_first_header:
            in_target_table = True
            continue
        if in_target_table:
            if "---" in line:
                continue
            rows.append(cells)
            if len(rows) >= limit:
                break
    return rows


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


def normalize_candidate_audit_display_text(value: object) -> str:
    text = str(value or "")
    replacements = {
        "通過正式分析門檻：至少 2 篇公司主題證據、2 個以上來源，且證據信心達高分": (
            "通過候選入選門檻：至少 2 篇公司主題證據、2 個以上來源，且入選支持度達高分；"
            "正式分析可信度仍需另看風險/機會歸因、財報、估值與公司文件"
        ),
        "通過正式分析門檻": "通過候選入選門檻",
        "證據信心": "入選支持度",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def candidate_payload_confidence_text(candidate: dict) -> str:
    score = candidate.get("evidence_confidence_score")
    label = candidate.get("evidence_confidence_label") or "未評分"
    latest = candidate.get("latest_evidence_date")
    if score is None:
        confidence = label
    else:
        confidence = format_confidence_score(float(score))
        if label and not confidence.startswith(str(label)):
            confidence = f"{label} {int(float(score))}"
    if latest:
        confidence += f"，最新 {latest}"
    age = candidate.get("evidence_age_days")
    if candidate.get("evidence_stale") and age is not None:
        confidence += f"（距今約 {int(age)} 天，超過 180 天）"
    return confidence


def candidate_payload_stale_note(candidate: dict) -> str:
    if not candidate.get("evidence_stale"):
        return ""
    latest = candidate.get("latest_evidence_date") or "未標示日期"
    age = candidate.get("evidence_age_days")
    age_text = f"距今約 {int(age)} 天，" if age is not None else ""
    return f"最新候選來源為 {latest}，{age_text}已超過 180 天新鮮度門檻。"


def candidate_source_matches_display_entity(candidate: dict, source: dict) -> bool:
    haystack = " ".join(
        str(source.get(field) or "")
        for field in ("title", "publisher", "url")
    ).lower()
    if is_low_quality_investor_forum_source(
        title=source.get("title"),
        publisher=source.get("publisher"),
        url=source.get("url"),
    ):
        return False
    ticker = str(candidate.get("ticker") or "")
    name = str(candidate.get("name") or "")
    if name == "南亞" and "南亞科" in haystack and ticker not in haystack:
        return False
    return True


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


def candidate_audit_html(markdown: str, result: Optional[dict] = None) -> str:
    candidates = result.get("candidate_whitelist", []) if result else []
    rows = []
    if candidates:
        status_labels = {
            "evidence_supported": "正式分析",
            "weak_evidence": "弱證據觀察",
            "needs_evidence": "待補證據",
            "evidence_limited": "補查後未升格",
            "evidence_unavailable": "資料不足排除",
        }
        for candidate in candidates:
            raw_sources = candidate.get("evidence_sources") or []
            evidence_sources = [
                source
                for source in raw_sources
                if candidate_source_matches_display_entity(candidate, source)
            ]
            filtered_source_count = max(0, len(raw_sources) - len(evidence_sources))
            filtered_note = (
                f"已排除 {filtered_source_count} 筆疑似同名或非本公司的來源。"
                if filtered_source_count
                else ""
            )
            source_summary = "；".join(
                " / ".join(
                    part
                    for part in [
                        str(source.get("title") or ""),
                        str(source.get("publisher") or ""),
                        str(source.get("published_at") or ""),
                    ]
                    if part
                )
                for source in evidence_sources[:2]
            )
            rows.append(
                [
                    f"{candidate.get('ticker')} {candidate.get('name')}",
                    candidate.get("segment") or "未分類",
                    status_labels.get(candidate.get("status"), "待補證據"),
                    (
                        f"{int(candidate.get('evidence_count') or 0)} 篇 / "
                        f"{int(candidate.get('evidence_source_count') or 0)} 來源"
                        + (f"（排除 {filtered_source_count}）" if filtered_source_count else "")
                    ),
                    normalize_candidate_audit_display_text(
                        f"{candidate_payload_stale_note(candidate)}"
                        f"{filtered_note}"
                        f"{candidate.get('validation_reason') or ''}"
                    ),
                    normalize_candidate_audit_display_text(candidate.get("next_action") or ""),
                    source_summary,
                    candidate_payload_confidence_text(candidate),
                ]
            )
    else:
        rows = markdown_table_rows_by_header(markdown, "候選公司審計", "股票", limit=30)
    if not rows:
        return ""

    supported = [row for row in rows if len(row) > 2 and "正式分析" in row[2]]
    weak = [row for row in rows if len(row) > 2 and "弱證據" in row[2]]
    needs = [row for row in rows if len(row) > 2 and "待補" in row[2]]
    limited = [row for row in rows if len(row) > 2 and "補查後未升格" in row[2]]
    unavailable = [row for row in rows if len(row) > 2 and "資料不足排除" in row[2]]
    cards = []
    for row in rows:
        stock = escape(row[0]) if len(row) > 0 else "-"
        segment = escape(row[1]) if len(row) > 1 else "-"
        status_raw = row[2] if len(row) > 2 else "待補證據"
        status = escape(status_raw)
        evidence = escape(row[3]) if len(row) > 3 else "-"
        reason = escape(row[4]) if len(row) > 4 else ""
        next_action = escape(row[5]) if len(row) > 5 else ""
        source_summary = escape(row[6]) if candidates and len(row) > 6 else ""
        confidence = escape(row[7] if candidates and len(row) > 7 else row[6] if not candidates and len(row) > 6 else "")
        status_class = (
            "audit-supported"
            if "正式分析" in status_raw
            else "audit-weak"
            if "弱證據" in status_raw
            else "audit-limited"
            if "補查後未升格" in status_raw
            else "audit-unavailable"
            if "資料不足排除" in status_raw
            else "audit-needs"
        )
        cards.append(
            f"""
            <article class="audit-card {status_class}">
              <div>
                <div class="ticker">{stock}</div>
                <div class="reason">{segment}</div>
                <div class="audit-reason">{reason}</div>
                <div class="audit-next">{next_action}</div>
                {"<div class='audit-source'>" + source_summary + "</div>" if source_summary else ""}
              </div>
              <div class="audit-meta">
                <span>{status}</span>
                <span>{evidence}</span>
                {"<span>" + confidence + "</span>" if confidence else ""}
              </div>
            </article>
            """
        )
    summary = (
        "<div class='audit-summary'>"
        f"<span>候選卡片 {len(rows)}</span>"
        f"<span>正式分析 {len(supported)}</span>"
        f"<span>弱證據 {len(weak)}</span>"
        f"<span>待補證據 {len(needs)}</span>"
        f"<span>補查後未升格 {len(limited)}</span>"
        f"<span>資料不足排除 {len(unavailable)}</span>"
        "</div>"
    )
    return summary + "".join(cards)


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
    return f"""
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ --navy:#0f172a; --blue:#1e3a8a; --teal:#0f766e; --amber:#92400e; --danger:#b42318; --surface:#ffffff; --bg:#edf2f7; --text:#0f172a; --muted:#475569; --border:#cbd5e1; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--text); background:var(--bg); }}
  .report {{ max-width:1360px; margin:0 auto; padding:18px 12px 34px; }}
  .hero {{ background:var(--navy); color:#f8fafc; border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:22px 24px 24px; box-shadow:0 14px 34px rgba(15,23,42,0.16); }}
  .kicker {{ color:#99f6e4; font-weight:700; font-size:14px; margin-bottom:6px; }}
  h1 {{ font-size:28px; line-height:1.25; margin:0 0 10px; letter-spacing:0; color:inherit; }}
  h2 {{ font-size:18px; margin:0 0 10px; }}
  .muted {{ color:#475569; }}
  .hero .muted {{ color:#cbd5e1; }}
  .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:14px; }}
  .trust-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin-top:10px; }}
  .metric {{ background:#FFFFFF; border:1px solid var(--border); border-radius:8px; padding:14px; }}
  .hero .metric {{ background:rgba(255,255,255,0.08); border-color:rgba(255,255,255,0.16); color:#f8fafc; }}
  .metric span {{ display:block; color:#475569; font-size:13px; font-weight:700; }}
  .hero .metric span {{ color:#cbd5e1; }}
  .metric strong {{ display:block; margin-top:4px; font-size:20px; }}
  .status {{ display:inline-block; border-radius:999px; padding:6px 10px; font-size:13px; font-weight:700; }}
  .ready {{ background:#E4F8F0; color:#087443; }}
  .caution {{ background:#FFF4DA; color:#8A5A12; }}
  .insufficient {{ background:#FDEAE7; color:#B42318; }}
  .unknown {{ background:#E8EEF6; color:#344054; }}
  .report-grid {{ display:block; margin-top:14px; }}
  .decision-rail {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:14px 0 4px; }}
  .rail-block {{ background:#FFFFFF; border:1px solid var(--border); border-left:4px solid #1e3a8a; border-radius:8px; padding:14px; box-shadow:0 3px 10px rgba(15,23,42,0.04); }}
  .rail-block:nth-child(2) {{ border-left-color:#0f766e; }}
  .rail-block:nth-child(3) {{ border-left-color:#92400e; }}
  .rail-block strong {{ display:block; font-size:13px; color:#0f172a; margin-bottom:6px; }}
  .rail-block p {{ margin:0; color:#475569; line-height:1.55; font-size:13px; }}
  .report-main {{ min-width:0; }}
  .panel {{ background:transparent; border:0; border-bottom:1px solid #cbd5e1; border-radius:0; padding:18px 0; margin-top:0; }}
  .panel:first-child {{ padding-top:0; }}
  .quality-issues {{ border:1px solid #cbd5e1; border-left:5px solid #1e3a8a; border-radius:8px; padding:16px; margin:0 0 10px; background:#ffffff; }}
  .quality-blockers {{ border-color:#F2A09A; border-left-color:#B42318; background:#FFF7F5; }}
  .quality-blockers strong {{ color:#B42318; }}
  .quality-warnings {{ border-color:#F5C97B; border-left-color:#92400E; background:#FFFCF2; }}
  .quality-warnings strong {{ color:#92400E; }}
  .quality-actions-only {{ border-color:#ADC8FF; border-left-color:#1E3A8A; background:#F6F9FF; }}
  .quality-actions-only strong {{ color:#1E3A8A; }}
  .quality-observations {{ border-color:#B9E4D2; border-left-color:#087443; background:#F4FBF8; }}
  .quality-observations strong {{ color:#087443; }}
  .quality-actions {{ margin-top:12px; border-top:1px solid #D7DEE8; padding-top:12px; }}
  .quality-actions strong {{ display:block; margin-bottom:2px; }}
  .next-step-group {{ background:#FFFFFF; border:1px solid var(--border); border-radius:8px; padding:14px; margin:10px 0; }}
  .next-step-group strong {{ display:block; color:#0f172a; margin-bottom:6px; }}
  .next-step-group ul {{ margin-top:6px; }}
  .auto-follow-up {{ background:#FFFFFF; border:1px solid #B9D7FE; border-left:5px solid #1E3A8A; border-radius:8px; padding:14px 16px; margin-top:12px; box-shadow:0 3px 10px rgba(15,23,42,0.04); }}
  .auto-follow-up strong {{ display:block; color:#1E3A8A; margin-bottom:4px; }}
  .auto-follow-up p {{ margin:0; color:#334155; line-height:1.55; }}
  .auto-paused {{ border-color:#F5C97B; border-left-color:#92400E; }}
  .auto-paused strong {{ color:#92400E; }}
  .auto-failed {{ border-color:#F2A09A; border-left-color:#D92D20; }}
  .auto-failed strong {{ color:#B42318; }}
  ul {{ margin:8px 0 0; padding-left:20px; }}
  li {{ margin:7px 0; line-height:1.55; }}
  .stock-list {{ display:grid; gap:10px; }}
  .stock-card {{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; border:1px solid var(--border); border-radius:8px; padding:14px; background:#FFFFFF; }}
  .stock-meta {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:2px 0 8px; color:#344054; font-size:12px; font-weight:700; }}
  .stock-meta span,.stock-meta strong {{ border-radius:999px; padding:4px 8px; background:#F4F7FB; color:#344054; }}
  .stock-meta strong.price-action {{ background:#E4F8F0; color:#087443; }}
  .stock-meta strong.price-watch {{ background:#FFF4DA; color:#8A5A12; }}
  .stock-meta strong.price-risk {{ background:#FDEAE7; color:#B42318; }}
  .stock-meta strong.price-neutral {{ background:#EEF2F6; color:#344054; }}
  .task-card {{ display:flex; justify-content:space-between; gap:14px; border:1px solid var(--border); border-radius:8px; padding:14px; background:#F9FBFD; margin:8px 0; }}
  .task-meta {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; align-content:flex-start; min-width:220px; }}
  .task-meta span {{ background:#E7F0FF; color:#1D4ED8; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:700; }}
  .audit-summary {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }}
  .audit-summary span {{ background:#F4F7FB; border:1px solid #D7DEE8; border-radius:999px; padding:6px 10px; font-size:13px; color:#344054; font-weight:700; }}
  .audit-card {{ display:flex; justify-content:space-between; gap:14px; border:1px solid var(--border); border-radius:8px; padding:14px; background:#FFFFFF; margin:8px 0; }}
  .audit-card.audit-supported {{ border-left:4px solid #0E9F6E; }}
  .audit-card.audit-weak {{ border-left:4px solid #F59E0B; }}
  .audit-card.audit-needs {{ border-left:4px solid #667085; }}
  .audit-card.audit-limited {{ border-left:4px solid #8A5A12; background:#FFFCF2; }}
  .audit-card.audit-unavailable {{ border-left:4px solid #98A2B3; background:#F8FAFC; }}
  .audit-reason {{ margin-top:8px; color:#344054; font-size:13px; line-height:1.45; }}
  .audit-next {{ margin-top:5px; color:#53657D; font-size:13px; line-height:1.45; }}
  .audit-source {{ margin-top:8px; color:#667085; font-size:12px; line-height:1.45; border-top:1px solid #EAECF0; padding-top:8px; }}
  .audit-meta {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; align-content:flex-start; min-width:180px; }}
  .audit-meta span {{ background:#F4F7FB; color:#344054; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:700; }}
  .matrix-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
  .matrix-summary {{ grid-column:1/-1; display:flex; gap:8px; flex-wrap:wrap; margin-bottom:2px; }}
  .matrix-summary span {{ background:#F4F7FB; border:1px solid #D7DEE8; border-radius:999px; padding:6px 10px; font-size:13px; color:#344054; font-weight:700; }}
  .matrix-card {{ border:1px solid var(--border); border-radius:8px; padding:14px; background:#FFFFFF; }}
  .matrix-card.decision-action {{ border-left:4px solid #0E9F6E; }}
  .matrix-card.decision-watch {{ border-left:4px solid #F59E0B; }}
  .matrix-card.decision-risk {{ border-left:4px solid #D92D20; }}
  .radar-card {{ border:1px solid var(--border); border-left:4px solid #0E9F6E; border-radius:8px; padding:14px; background:#FFFFFF; }}
  .radar-card.attention-known {{ border-left-color:#F59E0B; }}
  .matrix-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; }}
  .mini-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }}
  .mini-grid div {{ background:#F4F7FB; border-radius:8px; padding:8px; }}
  .mini-grid .valuation-high {{ background:#FFF4DA; }}
  .mini-grid .valuation-low {{ background:#E4F8F0; }}
  .mini-grid .risk-high {{ background:#FDEAE7; }}
  .mini-grid .risk-low {{ background:#E4F8F0; }}
  .mini-grid .price-action {{ background:#E4F8F0; }}
  .mini-grid .price-watch {{ background:#FFF4DA; }}
  .mini-grid .price-risk {{ background:#FDEAE7; }}
  .mini-grid .price-neutral {{ background:#EEF2F6; }}
  .mini-grid span {{ display:block; color:#344054; font-size:12px; font-weight:700; }}
  .mini-grid strong {{ display:block; margin-top:3px; color:#0f172a; font-size:14px; }}
  .thesis-list {{ display:grid; gap:10px; }}
  .thesis-card {{ border:1px solid #D7DEE8; border-radius:8px; padding:14px; background:#FFFFFF; }}
  .thesis-head {{ display:flex; justify-content:space-between; gap:12px; margin-bottom:10px; }}
  .thesis-body {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
  .thesis-body div {{ background:#F9FBFD; border:1px solid #EAECF0; border-radius:8px; padding:10px; }}
  .thesis-body span {{ display:block; color:#667085; font-size:12px; font-weight:700; margin-bottom:5px; }}
  .thesis-body p {{ margin:0; color:#344054; line-height:1.55; font-size:14px; }}
  .thesis-source {{ margin-top:10px; color:#667085; font-size:12px; line-height:1.5; border-top:1px solid #EAECF0; padding-top:10px; }}
  .credibility-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
  .credibility-card,.credibility-company {{ border:1px solid #D7DEE8; border-radius:8px; padding:14px; background:#FFFFFF; }}
  .credibility-company {{ border-left:4px solid #667085; margin:8px 0; }}
  .credibility-company.credibility-good {{ border-left-color:#0E9F6E; }}
  .credibility-company.credibility-caution {{ border-left-color:#F59E0B; }}
  .credibility-company.credibility-risk {{ border-left-color:#D92D20; }}
  .credibility-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; margin-bottom:8px; }}
  .credibility-card p {{ margin:0 0 8px; color:#344054; line-height:1.5; }}
  .credibility-card small,.credibility-company small {{ display:block; margin-top:8px; color:#667085; line-height:1.45; }}
  .credibility-badge {{ display:inline-flex; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:800; white-space:nowrap; background:#F4F7FB; color:#344054; }}
  .credibility-badge.credibility-good {{ background:#E4F8F0; color:#087443; }}
  .credibility-badge.credibility-caution {{ background:#FFF4DA; color:#8A5A12; }}
  .credibility-badge.credibility-risk {{ background:#FDEAE7; color:#B42318; }}
  .ticker {{ font-weight:800; margin-bottom:6px; }}
  .reason {{ color:#53657D; font-size:14px; line-height:1.5; }}
  .decision {{ white-space:nowrap; background:#E7F0FF; color:#1D4ED8; border-radius:999px; padding:6px 10px; font-weight:700; font-size:13px; }}
  .decision.decision-action {{ background:#E4F8F0; color:#087443; }}
  .decision.decision-watch {{ background:#FFF4DA; color:#8A5A12; }}
  .decision.decision-risk {{ background:#FDEAE7; color:#B42318; }}
  .decision.attention-low {{ background:#E4F8F0; color:#087443; }}
  .decision.attention-known {{ background:#FFF4DA; color:#8A5A12; }}
  details {{ background:#F9FBFD; border:1px solid var(--border); border-radius:8px; padding:12px 14px; margin:8px 0; }}
  summary {{ cursor:pointer; font-weight:700; }}
  .company-detail {{ background:#FFFFFF; margin:10px 0 0; }}
  .company-detail summary {{ color:#1D4ED8; }}
  @media (max-width:900px) {{ .decision-rail {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
  @media (max-width:760px) {{ .grid,.trust-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .matrix-list,.thesis-body,.credibility-grid {{ grid-template-columns:1fr; }} .stock-card,.task-card,.audit-card,.matrix-top,.credibility-head {{ display:block; }} .decision,.task-meta,.audit-meta,.credibility-badge {{ display:inline-flex; margin-top:10px; justify-content:flex-start; min-width:0; }} }}
  @media (max-width:520px) {{ .grid,.trust-grid,.mini-grid,.decision-rail {{ grid-template-columns:1fr; }} }}
</style>
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


def candidate_revalidation_summary(result: dict) -> dict:
    rerun = result.get("rerun_report")
    rerun = rerun if isinstance(rerun, dict) else {}
    revalidation = rerun.get("candidate_revalidation") or {}
    candidates = revalidation.get("candidate_whitelist") or []
    promoted = set(revalidation.get("promoted_tickers") or [])
    supported = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "evidence_supported"
    ]
    weak = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "weak_evidence"
    ]
    needs = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "needs_evidence"
    ]
    limited = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "evidence_limited"
    ]
    unavailable = [
        candidate
        for candidate in candidates
        if candidate.get("status") == "evidence_unavailable"
    ]
    return {
        "changed": bool(revalidation.get("changed")),
        "total": len(candidates),
        "promoted_count": len(promoted) if promoted else len(supported),
        "weak_count": len(weak),
        "needs_evidence_count": len(needs),
        "limited_count": len(limited),
        "unavailable_count": len(unavailable),
        "document_query_count": int(revalidation.get("document_query_count") or 0),
        "document_count": int(revalidation.get("document_count") or 0),
        "newly_promoted": revalidation.get("newly_promoted") or [],
        "no_longer_promoted": revalidation.get("no_longer_promoted") or [],
        "status_changes": revalidation.get("status_changes") or [],
        "rows": [
            {
                "股票": f"{candidate.get('ticker')} {candidate.get('name')}",
                "產業位置": candidate.get("segment"),
                "狀態": {
                    "evidence_supported": "正式分析",
                    "weak_evidence": "弱證據",
                    "needs_evidence": "待補證據",
                    "evidence_limited": "補查後未升格",
                    "evidence_unavailable": "資料不足排除",
                }.get(candidate.get("status"), "待補證據"),
                "證據": f"{candidate.get('evidence_count', 0)} 篇 / {candidate.get('evidence_source_count', 0)} 來源",
                "原因": candidate.get("validation_reason") or "-",
                "下一步": candidate.get("next_action") or "-",
            }
            for candidate in candidates
        ],
    }


def maintenance_service_metrics(status: dict, service_snapshot: dict) -> dict:
    confidence = service_snapshot.get("candidate_confidence") or {}
    high_threshold = confidence.get("high_threshold")
    return {
        "資料庫": "正常" if status.get("integrity", {}).get("ok", True) else "異常",
        "Redis": "正常" if service_snapshot.get("redis", {}).get("ok") else "未連線",
        "AI Key": service_snapshot.get("gemini", {}).get("key_count", 0),
        "市場資料": "可用" if service_snapshot.get("finmind", {}).get("mode") else "檢查",
        "升格門檻": format_confidence_score(float(high_threshold)) if high_threshold is not None else "未評估",
    }


def upgrade_audit_html(audit: dict) -> str:
    summary = audit.get("summary") or {}
    status = str(audit.get("overall_status") or "unknown")
    implementation = audit.get("implementation") or {}
    deployment = audit.get("deployment") or {}
    implementation_status = str(
        implementation.get("status") or summary.get("implementation_status") or "unknown"
    )
    deployment_status = str(deployment.get("status") or summary.get("deployment_status") or "unknown")
    status_labels = {
        "ready": "通過",
        "caution": "注意",
        "failed": "需處理",
        "unknown": "未評估",
    }
    strict_label = "正式部署" if audit.get("strict_external") else "一般檢查"
    total = int(summary.get("total_checks") or 0)
    ready = int(summary.get("ready") or 0)
    warnings = int(summary.get("warnings") or 0)
    optional_warnings = int(summary.get("optional_warnings") or 0)
    failures = int(summary.get("failures") or 0)
    implementation_ready = int(implementation.get("ready") or 0)
    implementation_total = int(implementation.get("total_checks") or 0)
    deployment_ready = int(deployment.get("ready") or 0)
    deployment_total = int(deployment.get("total_checks") or 0)
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    area_cards = []
    for area_key, area in sorted((audit.get("areas") or {}).items()):
        area_cards.append(
            '<div class="upgrade-audit-area"><strong>{label}</strong>'
            "<span>通過 {ready} / 注意 {warnings} / 需處理 {failures}</span></div>".format(
                label=escape(area_labels.get(area_key, str(area_key))),
                ready=int(area.get("ready") or 0),
                warnings=int(area.get("warnings") or 0),
                failures=int(area.get("failures") or 0),
            )
        )
    return """
    <div class="result-shell">
        <div class="section-title">升級稽核</div>
        <div class="upgrade-audit-grid">
            <div class="upgrade-audit-tile">
                <span>核心升級</span>
                <strong><span class="upgrade-audit-status {implementation_status_class}">{implementation_status_label}</span></strong>
            </div>
            <div class="upgrade-audit-tile">
                <span>外部整合</span>
                <strong><span class="upgrade-audit-status {deployment_status_class}">{deployment_status_label}</span></strong>
            </div>
            <div class="upgrade-audit-tile"><span>檢查模式</span><strong>{strict_label}</strong></div>
            <div class="upgrade-audit-tile"><span>通過項目</span><strong>{ready}/{total}</strong></div>
        </div>
        <div class="upgrade-audit-note">
            整體狀態：{status_label}；核心 {implementation_ready}/{implementation_total} 通過，外部 {deployment_ready}/{deployment_total} 通過；注意 {warnings} 項、外部選配 {optional_warnings} 項、需處理 {failures} 項。
        </div>
        <div class="upgrade-audit-areas">{areas}</div>
    </div>
    """.format(
        status_label=escape(status_labels.get(status, status)),
        implementation_status_class=escape(
            implementation_status if implementation_status in {"ready", "caution", "failed"} else "unknown"
        ),
        implementation_status_label=escape(status_labels.get(implementation_status, implementation_status)),
        deployment_status_class=escape(
            deployment_status if deployment_status in {"ready", "caution", "failed"} else "unknown"
        ),
        deployment_status_label=escape(status_labels.get(deployment_status, deployment_status)),
        strict_label=escape(strict_label),
        ready=ready,
        total=total,
        implementation_ready=implementation_ready,
        implementation_total=implementation_total,
        deployment_ready=deployment_ready,
        deployment_total=deployment_total,
        warnings=warnings,
        optional_warnings=optional_warnings,
        failures=failures,
        areas="".join(area_cards) or "<div class='upgrade-audit-area'><strong>未評估</strong><span>尚無稽核資料</span></div>",
    )


def upgrade_audit_rows(audit: dict) -> list[dict]:
    severity_labels = {"pass": "通過", "warn": "注意", "fail": "需處理"}
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    return [
        {
            "面向": area_labels.get(str(check.get("area")), check.get("area")),
            "能力": check.get("label") or check.get("capability"),
            "結果": severity_labels.get(str(check.get("severity")), check.get("severity")),
            "目前狀態": check.get("status"),
            "說明": check.get("detail") or "-",
            "處理方向": check.get("remediation") or "-",
        }
        for check in audit.get("checks") or []
    ]


def follow_up_result_message(result: dict, summary_text: str) -> tuple[str, str]:
    rerun = result.get("rerun_report")
    rerun = rerun if isinstance(rerun, dict) else {}
    if rerun.get("report_id"):
        return "success", f"{summary_text}，已產生新報告 #{rerun['report_id']}。"
    if rerun.get("status") == "skipped":
        blockers = "；".join(rerun.get("blockers") or [])
        reason = rerun.get("reason") or "補資料後仍有關鍵缺口，先不重新產生報告。"
        detail = f"（{blockers}）" if blockers else ""
        return "warning", f"{summary_text}，{reason}{detail}"
    return "success", f"{summary_text}，補強任務已完成。"


def follow_up_check_value_text(value: Optional[dict]) -> str:
    if not value:
        return "-"
    labels = {
        "stored_count": "已取得",
        "error_count": "錯誤",
        "blocked_tickers": "仍缺公司",
        "min_days": "至少天數",
        "min_months": "至少月份",
        "min_years": "至少年數",
        "min_records": "至少筆數",
        "min_documents": "至少文件",
        "status": "狀態",
        "manual_review": "需人工覆核",
    }
    parts = []
    for key, raw_value in value.items():
        label = labels.get(key, key)
        if isinstance(raw_value, list):
            display = "、".join(str(item) for item in raw_value) if raw_value else "無"
        elif isinstance(raw_value, bool):
            display = "是" if raw_value else "否"
        else:
            display = str(raw_value)
        parts.append(f"{label} {display}")
    return "；".join(parts)


def follow_up_blocker_action_rows(result: dict) -> list[dict]:
    rows = []
    rerun = result.get("rerun_report")
    rerun = rerun if isinstance(rerun, dict) else {}
    rerun_actions = rerun.get("next_actions") or []
    action_sources = [{"next_actions": rerun_actions}] if rerun_actions else (result.get("results") or {}).values()
    for task_result in action_sources:
        if not isinstance(task_result, dict):
            continue
        for action in task_result.get("next_actions") or []:
            rows.append(
                {
                    "股票": action.get("ticker") or "-",
                    "公司": action.get("company_name") or "-",
                    "下一步": {
                        "manual_company_filing_import": "人工匯入官方文件",
                        "retry_company_filing_search": "稍後自動重試",
                        "broaden_company_filing_search": "擴大官方搜尋",
                        "complete_follow_up_check": "補齊未達標資料",
                    }.get(action.get("action"), action.get("action") or "-"),
                    "缺必要文件": "、".join(action.get("missing_required_types") or []),
                    "缺建議文件": "、".join(action.get("missing_recommended_types") or []),
                    "目前": follow_up_check_value_text(action.get("observed")),
                    "要求": follow_up_check_value_text(action.get("required")),
                    "原因": action.get("reason") or "-",
                }
            )
    if rows:
        return rows
    for blocker in rerun.get("blockers") or []:
        rows.append(
            {
                "股票": "-",
                "公司": "-",
                "下一步": "補齊資料後再重跑",
                "缺必要文件": "-",
                "缺建議文件": "-",
                "目前": "-",
                "要求": "-",
                "原因": blocker,
            }
        )
    return rows


def render_reader_report(markdown: str, result: Optional[dict] = None) -> None:
    components.html(report_html(markdown, result), height=820, scrolling=True)


def candidate_rows(candidates: list[dict]) -> list[dict]:
    rows = []
    status_labels = {
        "evidence_supported": "已驗證",
        "weak_evidence": "弱證據",
        "needs_evidence": "待補資料",
        "evidence_limited": "補查後未升格",
        "evidence_unavailable": "資料不足排除",
    }
    for candidate in candidates:
        rows.append(
            {
                "股票": f"{candidate.get('ticker')} {candidate.get('name')}",
                "產業位置": candidate.get("segment"),
                "來源數": candidate.get("evidence_count"),
                "來源家數": candidate.get("evidence_source_count"),
                "狀態": status_labels.get(candidate.get("status"), "待補資料"),
                "原因": candidate.get("validation_reason"),
                "下一步": candidate.get("next_action"),
                "證據信心": (
                    f"{candidate.get('evidence_confidence_label') or '未評分'} "
                    f"{candidate.get('evidence_confidence_score', '-')}"
                ),
                "主要來源": "；".join(
                    source.get("title", "")
                    for source in candidate.get("evidence_sources", [])[:2]
                )
                or "；".join(candidate.get("evidence_titles", [])[:2]),
            }
        )
    return rows


def render_market_errors(result: dict) -> None:
    errors = []
    for key, label in [
        ("market_errors", "股價"),
        ("monthly_revenue_errors", "月營收"),
    ]:
        for item in result.get(key, []) or []:
            errors.append(
                {
                    "資料類型": label,
                    "股票": item.get("ticker"),
                    "資料集": item.get("dataset"),
                    "原因": item.get("error"),
                }
            )
    if not errors:
        return
    st.warning("部分市場資料未抓到；報告已用可取得資料完成，缺資料股票會降低判斷信心。")
    st.dataframe(errors, width="stretch", hide_index=True)


def render_source_audit(result: dict) -> None:
    audit = result.get("source_audit")
    if not isinstance(audit, dict):
        st.info("此份舊報告沒有來源追蹤紀錄。")
        return

    fixed_sources = audit.get("fixed_sources") or {}
    dynamic_queries = audit.get("dynamic_queries") or {}
    candidate_support = audit.get("candidate_support") or {}
    remediation = audit.get("remediation") or {}
    plan_quality = audit.get("plan_quality") or {}
    dynamic_entity_backfill = audit.get("dynamic_entity_backfill") or {}
    cols = st.columns(4)
    cols[0].metric("固定來源入庫", fixed_sources.get("stored_count", 0))
    cols[1].metric("AI 查詢入庫", dynamic_queries.get("stored_count", 0))
    cols[2].metric("AI 查詢數", audit.get("dynamic_query_count", 0))
    cols[3].metric("來源錯誤", audit.get("total_error_count", 0))

    st.caption(
        f"深度分析：{'開啟' if audit.get('deep_analysis') else '關閉'}｜"
        f"國際來源：{'納入' if audit.get('include_international') else '未納入'}｜"
        f"每來源抓取上限：{audit.get('limit_per_query')}｜"
        f"摘要使用證據上限：{audit.get('evidence_limit')}"
    )
    support_ratio = candidate_support.get("supported_ratio", 0)
    st.caption(
        f"候選公司證據覆蓋：{candidate_support.get('supported', 0)}/"
        f"{candidate_support.get('total', 0)}（{support_ratio:.0%}）｜"
        f"弱證據：{candidate_support.get('weak', 0)}｜"
        f"自動補資料：{'已觸發' if remediation.get('supplemented') else '未觸發'}"
    )
    if dynamic_entity_backfill:
        st.caption(
            "動態公司證據入庫："
            f"更新 {dynamic_entity_backfill.get('updated_documents', 0)} 篇、"
            f"新增/合併 {dynamic_entity_backfill.get('matches_added', 0)} 個公司對應"
        )
    if isinstance(plan_quality, dict) and plan_quality:
        st.caption(
            f"拆解任務品質：{plan_quality.get('status', 'unknown')}｜"
            f"分數：{plan_quality.get('score', 0)}｜"
            f"{plan_quality.get('recommendation', '')}"
        )
        missing = plan_quality.get("missing") or []
        if missing:
            st.warning("拆解任務缺口：" + "；".join(missing[:6]))
        query_quality = plan_quality.get("query_quality") or {}
        if query_quality:
            st.caption(
                f"查詢品質：對齊 {query_quality.get('aligned_queries', 0)}/"
                f"{query_quality.get('total_queries', 0)}｜"
                f"國際查詢 {query_quality.get('international_query_count', 0)}｜"
                f"籠統查詢 {query_quality.get('generic_query_count', 0)}"
            )
            query_quality_rows = []
            for name, detail in (query_quality.get("subtopics") or {}).items():
                query_quality_rows.append(
                    {
                        "子題": name,
                        "查詢數": detail.get("query_count", 0),
                        "語言": "、".join(detail.get("languages", [])),
                        "國際查詢": "有" if detail.get("has_international_query") else "缺少",
                        "籠統查詢": "；".join(detail.get("generic_queries", [])),
                        "未對齊查詢": "；".join(detail.get("unaligned_queries", [])),
                    }
                )
            if query_quality_rows:
                with st.expander("AI 查詢品質檢查"):
                    st.dataframe(query_quality_rows, width="stretch", hide_index=True)

    rows = []
    for source_type, summary in [
        ("固定資料源", fixed_sources),
        ("AI 動態查詢", dynamic_queries),
    ]:
        rows.append(
            {
                "類型": source_type,
                "執行來源數": summary.get("source_runs", 0),
                "入庫篇數": summary.get("stored_count", 0),
                "錯誤數": summary.get("error_count", 0),
                "樣本標題": "；".join(summary.get("sample_titles", [])[:3]),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)
    query_type_counts = audit.get("query_type_counts") or {}
    query_type_labels = audit.get("query_type_labels") or {}
    if query_type_counts:
        st.markdown("**AI 查詢來源分布**")
        st.dataframe(
            [
                {
                    "查詢類型": (query_type_labels.get(query_type) or {}).get("label", query_type),
                    "數量": count,
                    "說明": (query_type_labels.get(query_type) or {}).get("description", ""),
                }
                for query_type, count in query_type_counts.items()
            ],
            width="stretch",
            hide_index=True,
        )
    fixed_selection = (fixed_sources.get("source_selection") or {}).get("selected_sample") or []
    if fixed_selection:
        st.markdown("**固定資料源抓取清單樣本**")
        st.dataframe(
            [
                {
                    "來源": item.get("name"),
                    "類別": item.get("category"),
                    "抓取 URL": item.get("url"),
                    "資料意圖": "、".join(item.get("source_intents") or []),
                    "命中詞": "、".join(item.get("match_terms") or []),
                }
                for item in fixed_selection
            ],
            width="stretch",
            hide_index=True,
        )
    if remediation.get("supplemented"):
        st.info(
            f"第一次抓取後資料覆蓋不足，系統已自動補抓 "
            f"{remediation.get('supplemental_query_count', 0)} 組查詢。"
        )
        remediation_rows = [
            {
                "補抓回合": round_item.get("round"),
                "新增查詢": round_item.get("query_count"),
                "新增入庫": round_item.get("stored_count"),
                "原因": round_item.get("reason"),
            }
            for round_item in remediation.get("rounds", [])
        ]
        if remediation_rows:
            st.dataframe(remediation_rows, width="stretch", hide_index=True)

    query_metadata_sample = audit.get("query_metadata_sample") or []
    query_sample = audit.get("dynamic_query_sample") or []
    if query_metadata_sample:
        st.markdown("**AI 本次產生的資料查詢樣本**")
        st.dataframe(
            [
                {
                    "查詢": item.get("query"),
                    "語言": item.get("language", "-"),
                    "證據類型": item.get("evidence_type", "-"),
                    "驗證假設": item.get("hypothesis", "-"),
                }
                for item in query_metadata_sample
            ],
            width="stretch",
            hide_index=True,
        )
    elif query_sample:
        st.markdown("**AI 本次產生的資料查詢樣本**")
        st.dataframe(
            [{"查詢來源": url} for url in query_sample],
            width="stretch",
            hide_index=True,
        )


def render_quality_gate(result: dict) -> None:
    gate = result.get("quality_gate")
    if not isinstance(gate, dict):
        return
    status = gate.get("status", "unknown")
    label_map = {
        "ready": "資料品質可用",
        "caution": "需謹慎判讀",
        "insufficient": "資料不足",
    }
    if status == "ready":
        st.success(gate.get("recommendation", label_map["ready"]))
    elif status == "caution":
        st.warning(gate.get("recommendation", label_map["caution"]))
    else:
        st.error(gate.get("recommendation", label_map["insufficient"]))

    metrics = gate.get("metrics") or {}
    action_policy = gate.get("action_policy") or {}
    cols = st.columns(4)
    cols[0].metric("品質狀態", label_map.get(status, status))
    cols[1].metric("正式股票", metrics.get("promoted_count", 0))
    cols[2].metric("正式證據", f"{float(metrics.get('candidate_supported_ratio') or 0):.0%}")
    amount = action_policy.get("max_deployable_amount")
    cols[3].metric("品質額度上限", f"{int(amount):,}" if amount is not None else "-")
    source_cols = st.columns(6)
    lookback_days = metrics.get("source_lookback_days")
    recent_label = f"近 {int(lookback_days)} 天來源" if lookback_days else "近況來源"
    source_cols[0].metric("來源篇數", metrics.get("dynamic_source_count", 0))
    source_cols[1].metric("來源家數", metric_int(metrics.get("source_unique_publishers")))
    source_cols[2].metric("來源有日期", metric_percent(metrics.get("source_timestamp_coverage")))
    source_cols[3].metric(recent_label, metric_percent(metrics.get("source_recent_coverage")))
    source_cols[4].metric("近況訊號", metric_percent(metrics.get("leading_signal_coverage")))
    source_cols[5].metric("最低信心", confidence_label(metrics.get("formal_confidence_min")))
    llm_status = metrics.get("llm_analysis_status")
    if llm_status:
        st.caption("模型補充分析：" + ("已啟用" if llm_status == "enabled" else "改用資料規則判讀"))
    if action_policy.get("label"):
        st.caption(f"投資行動狀態：{action_policy['label']}")

    issues = []
    for item in gate.get("blockers", []) or []:
        issues.append({"等級": "阻擋", "項目": item})
    for item in gate.get("warnings", []) or []:
        issues.append({"等級": "警示", "項目": item})
    for item in gate.get("observations", []) or []:
        issues.append({"等級": "觀察", "項目": item})
    if issues:
        st.dataframe(issues, width="stretch", hide_index=True)
    actions = gate.get("remediation_actions") or []
    if actions:
        st.markdown("**系統建議補強**")
        for action in actions:
            st.markdown(f"- {action}")


def render_company_data_audit(report_id: int) -> None:
    try:
        audit = api_get(f"/reports/{report_id}/company-data-audit")
    except requests.RequestException as exc:
        st.warning(f"個股資料足夠性檢查失敗：{exc}")
        return
    summary = audit.get("summary") or {}
    cols = st.columns(4)
    cols[0].metric("檢查公司", summary.get("total", 0))
    cols[1].metric("足夠", summary.get("sufficient", 0))
    cols[2].metric("部分足夠", summary.get("partial", 0))
    cols[3].metric("不足", summary.get("insufficient", 0))
    rows = []
    status_labels = {
        "sufficient": "足夠",
        "partial": "部分足夠",
        "insufficient": "不足",
    }
    for row in audit.get("rows") or []:
        evidence = row.get("evidence") or {}
        filings = row.get("company_filings") or {}
        rows.append(
            {
                "股票": row.get("ticker"),
                "狀態": status_labels.get(row.get("status"), row.get("status")),
                "股價": (row.get("price") or {}).get("latest_date"),
                "月營收": (row.get("monthly_revenue") or {}).get("latest_date"),
                "財報期數": (row.get("financial_metrics") or {}).get("periods"),
                "估值": (row.get("valuation") or {}).get("latest_date"),
                "公司文件": filings.get("rows"),
                "高品質文件": filings.get("high_quality_rows"),
                "文件品質": filings.get("max_quality_score"),
                "報告文本": evidence.get("report_text_count"),
                "入庫文本": evidence.get("db_text_count"),
                "AI歸因": evidence.get("effective_finding_count"),
                "缺口": "；".join(row.get("missing") or []) or "無",
            }
        )
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    for note in audit.get("notes") or []:
        st.caption(note)


def render_follow_up_controls(report_id: int, markdown: str, scope: str = "report") -> None:
    key_suffix = f"{scope}_{report_id}"
    rows = markdown_table_rows(markdown, "自動補強任務", limit=20)
    planned_actions = []
    plan_next_actions = []
    plan_error = None
    try:
        plan = api_get(f"/reports/{report_id}/follow-up/plan")
        planned_actions = plan.get("actions") or []
        plan_next_actions = plan.get("next_actions") or []
        freshness = plan.get("freshness") or {}
    except requests.RequestException as exc:
        plan_error = str(exc)
        freshness = {}
    st.markdown("**自動補強**")
    if planned_actions:
        required_count = sum(1 for action in planned_actions if action.get("purpose") == "required")
        tracking_count = sum(1 for action in planned_actions if action.get("purpose") == "tracking")
        st.caption(f"資料缺口補強 {required_count} 項，追蹤更新 {tracking_count} 項。")
        st.dataframe(
            [
                {
                    "任務": action.get("label") or action.get("action_type", "-"),
                    "股票": "、".join(action.get("tickers") or []) or "全主題",
                    "性質": "資料缺口補強" if action.get("purpose") == "required" else "追蹤更新",
                    "優先級": action.get("priority", "-"),
                    "頻率": action.get("frequency", "-"),
                    "觸發原因": action.get("reason", "-"),
                }
                for action in planned_actions
            ],
            width="stretch",
            hide_index=True,
        )
        if plan_next_actions:
            st.caption("預計補強重點")
            st.dataframe(
                [
                    {
                        "股票": "、".join(action.get("tickers") or []) or "全主題",
                        "下一步": action.get("next_step"),
                        "補強目標": action.get("target") or "-",
                        "完成條件": action.get("completion_criteria") or "-",
                        "優先級": action.get("priority", "-"),
                        "原因": action.get("reason", "-"),
                    }
                    for action in plan_next_actions
                ],
                width="stretch",
                hide_index=True,
            )
    elif rows:
        st.dataframe(
            [
                {
                    "任務": row[0] if len(row) > 0 else "-",
                    "股票": row[1] if len(row) > 1 else "-",
                    "性質": row[2] if len(row) > 5 else "追蹤更新",
                    "優先級": row[3] if len(row) > 5 else row[2] if len(row) > 2 else "-",
                    "頻率": row[4] if len(row) > 5 else row[3] if len(row) > 3 else "-",
                    "觸發原因": row[5] if len(row) > 5 else row[4] if len(row) > 4 else "-",
                }
                for row in rows
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("目前沒有明確補強任務；仍可重新刷新資料並重跑一次，確認結論是否改變。")
        skipped = freshness.get("skipped_actions") or []
        if skipped:
            st.caption(f"已略過 {len(skipped)} 項追蹤更新，原因是相關資料仍在新鮮範圍內。")
            with st.expander("查看已略過的追蹤更新"):
                skipped_details = freshness.get("skipped_details") or []
                st.dataframe(
                    [
                        {
                            "任務": action.get("label") or action.get("action_type", "-"),
                            "股票": "、".join(action.get("tickers") or []) or "全主題",
                            "最新日期": "、".join(
                                f"{ticker}:{date_value}"
                                for ticker, date_value in ((action.get("freshness") or {}).get("latest_dates") or {}).items()
                            )
                            or "-",
                            "新鮮門檻": f"{(action.get('freshness') or {}).get('max_age_days')} 天"
                            if (action.get("freshness") or {}).get("max_age_days") is not None
                            else "-",
                            "原因": "資料仍在新鮮範圍內",
                        }
                        for action in (skipped_details or skipped)
                    ],
                    width="stretch",
                    hide_index=True,
                )
        if plan_error:
            st.caption("暫時無法讀取後端任務預覽。")
    skipped_actions = (freshness.get("skipped_actions") or []) if isinstance(freshness, dict) else []
    force_refresh = False
    if skipped_actions:
        force_refresh = st.checkbox(
            "忽略新鮮度，強制更新已略過的追蹤資料",
            value=False,
            key=f"followup_force_refresh_{key_suffix}",
        )
    purpose_options = {
        "全部任務": "all",
        "只補資料缺口": "required",
        "只做追蹤更新": "tracking",
    }
    default_purpose = "只補資料缺口" if planned_actions and any(
        action.get("purpose") == "required" for action in planned_actions
    ) else "只做追蹤更新"
    selected_purpose_label = st.radio(
        "執行範圍",
        options=list(purpose_options.keys()),
        index=list(purpose_options.keys()).index(default_purpose),
        horizontal=True,
        key=f"followup_purpose_{key_suffix}",
    )
    selected_purpose = purpose_options[selected_purpose_label]
    action_pool = planned_actions + skipped_actions if force_refresh else planned_actions
    if selected_purpose == "all":
        executable_actions = action_pool
    else:
        executable_actions = [
            action
            for action in action_pool
            if action.get("purpose") == selected_purpose
        ]
    manual_tracking_available = not planned_actions and not rows and plan_error is None
    manual_tracking_selected = manual_tracking_available and selected_purpose in {"all", "tracking"}
    has_executable_actions = bool(executable_actions or rows or manual_tracking_selected)
    if planned_actions and not executable_actions:
        st.caption("目前選擇的範圍沒有可執行任務。")
    elif manual_tracking_selected:
        st.caption("本次將執行：手動追蹤補抓資料；完成後可重新產生報告。")
    elif manual_tracking_available:
        st.caption("目前沒有資料缺口任務；可切換到追蹤更新後手動補抓資料。")
    elif executable_actions:
        selected_required = sum(1 for action in executable_actions if action.get("purpose") == "required")
        selected_tracking = sum(1 for action in executable_actions if action.get("purpose") == "tracking")
        st.caption(f"本次將執行：資料缺口補強 {selected_required} 項，追蹤更新 {selected_tracking} 項。")
    cols = st.columns([0.62, 0.38])
    rerun_report = cols[0].checkbox("完成後重新產生一份報告", value=True, key=f"followup_rerun_{key_suffix}")
    news_limit = cols[1].number_input(
        "補抓資料量",
        min_value=10,
        max_value=100,
        value=30,
        step=10,
        key=f"followup_news_limit_{key_suffix}",
    )
    button_label = (
        "補資料缺口並重跑"
        if selected_purpose == "required"
        else "執行追蹤更新並重跑"
        if selected_purpose == "tracking"
        else "執行全部補強並重跑"
    )
    if st.button(
        button_label,
        type="primary",
        key=f"followup_run_{key_suffix}",
        disabled=not has_executable_actions,
    ):
        try:
            task_response = api_task_post(
                f"/reports/{report_id}/follow-up/run_async",
                {
                    "rerun_report": bool(rerun_report),
                    "news_limit": int(news_limit),
                    "purpose": selected_purpose,
                    "force_refresh": bool(force_refresh or manual_tracking_selected),
                },
            )
            st.session_state["last_follow_up_task_id"] = task_response["task_id"]
            st.session_state.pop(f"refresh_followup_task_{key_suffix}_status", None)
            st.success(f"已送出補強背景任務：{task_response['task_id']}")
        except requests.RequestException as exc:
            st.error(f"自動補強任務送出失敗：{request_error_message(exc)}")

    last_follow_up_task_id = st.session_state.get("last_follow_up_task_id")
    if last_follow_up_task_id:
        with st.expander("背景補強任務狀態", expanded=True):
            task_id = st.text_input(
                "補強任務編號",
                value=last_follow_up_task_id,
                key=f"followup_task_lookup_{key_suffix}",
            )
            task_status = render_task_status_panel(
                task_id=task_id,
                refresh_key=f"refresh_followup_task_{key_suffix}",
            )
            result = (task_status or {}).get("result") if isinstance(task_status, dict) else None
            if isinstance(result, dict) and st.button("套用背景補強結果", key=f"apply_followup_task_{key_suffix}"):
                st.session_state["last_follow_up_result"] = result
                selected_summary = (result.get("summary") or {}).get("selected") or {}
                execution_summary = (result.get("summary") or {}).get("execution") or {}
                summary_text = (
                    f"執行 {selected_summary.get('total_count', len(result.get('actions') or []))} 項任務"
                    f"（資料缺口 {selected_summary.get('required_count', 0)}、"
                    f"追蹤更新 {selected_summary.get('tracking_count', 0)}）"
                )
                if execution_summary:
                    summary_text += (
                        f"，補入/更新 {execution_summary.get('stored_count', 0)} 筆資料"
                        f"，錯誤 {execution_summary.get('error_count', 0)} 項"
                    )
                message_level, message_text = follow_up_result_message(result, summary_text)
                st.session_state["follow_up_flash"] = {
                    "level": message_level,
                    "message": message_text,
                    "result": result,
                }
                new_report = result.get("rerun_report") or {}
                if new_report.get("report_id"):
                    st.session_state["pending_selected_report_id"] = int(new_report["report_id"])
                st.rerun()


def render_follow_up_flash() -> None:
    flash = st.session_state.get("follow_up_flash")
    if not isinstance(flash, dict):
        return
    message = flash.get("message", "補強任務已完成。")
    if flash.get("level") == "warning":
        st.warning(message)
    else:
        st.success(message)
    result = flash.get("result") or {}
    blocker_rows = follow_up_blocker_action_rows(result)
    if blocker_rows:
        with st.expander("查看重跑前需要處理的項目", expanded=True):
            st.dataframe(blocker_rows, width="stretch", hide_index=True)
    execution = ((result.get("summary") or {}).get("execution") or {})
    items = execution.get("items") or []
    if items:
        with st.expander("查看本次補強結果"):
            st.dataframe(
                [
                    {
                        "任務": item.get("task"),
                        "更新筆數": item.get("stored_count", 0),
                        "錯誤數": item.get("error_count", 0),
                        "完成狀態": "達標" if (item.get("completion") or {}).get("completed") else "未達標",
                        "來源": item.get("source") or "-",
                    }
                    for item in items
                ],
                width="stretch",
                hide_index=True,
            )
    revalidation = candidate_revalidation_summary(result)
    if revalidation["total"]:
        with st.expander("查看候選重新驗證結果", expanded=revalidation["changed"]):
            cols = st.columns(4)
            cols[0].metric("候選", revalidation["total"])
            cols[1].metric("正式", revalidation["promoted_count"])
            cols[2].metric("弱證據", revalidation["weak_count"])
            cols[3].metric("待補", revalidation["needs_evidence_count"])
            st.caption(
                f"本次重新驗證使用 {revalidation['document_query_count']} 組公司/主題查詢、"
                f"{revalidation['document_count']} 筆去重後文件。"
            )
            if revalidation["newly_promoted"]:
                st.success("新升格為正式分析：" + "、".join(revalidation["newly_promoted"]))
            if revalidation["no_longer_promoted"]:
                st.warning("降回觀察/待補：" + "、".join(revalidation["no_longer_promoted"]))
            st.dataframe(revalidation["rows"], width="stretch", hide_index=True)
    if st.button("關閉補強結果", key="dismiss_follow_up_flash"):
        st.session_state.pop("follow_up_flash", None)
        st.rerun()


def render_task_status(task_status: dict) -> None:
    cols = st.columns(4)
    cols[0].metric("Task", task_status.get("status", "UNKNOWN"))
    cols[1].metric("Ready", str(task_status.get("ready", False)))
    cols[2].metric("Success", str(task_status.get("successful", False)))
    run = task_status.get("run")
    cols[3].metric("Run", f"#{run['id']}" if isinstance(run, dict) and run.get("id") else "-")
    progress = task_status.get("progress") if isinstance(task_status.get("progress"), dict) else {}
    progress_pct = progress.get("progress_pct")
    if isinstance(progress_pct, (int, float)):
        st.progress(max(0.0, min(float(progress_pct), 1.0)))
    if progress:
        st.caption(
            "進度："
            f"{progress.get('status') or task_status.get('status', 'UNKNOWN')}｜"
            f"{progress.get('current_step') or progress.get('next_incomplete_step') or '等待中'}"
        )
        if progress.get("resume_hint"):
            st.caption(str(progress["resume_hint"]))
    if task_status.get("result"):
        st.json(task_status["result"])
    if task_status.get("error"):
        st.error(task_status["error"])
    if isinstance(run, dict):
        st.dataframe(
            [
                {
                    "run_id": run.get("id"),
                    "status": run.get("status"),
                    "report_id": run.get("report_id"),
                    "output_path": run.get("output_path"),
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                }
            ],
            width="stretch",
            hide_index=True,
        )


def _task_status_ready(task_status: dict | None) -> bool:
    if not isinstance(task_status, dict):
        return False
    return bool(task_status.get("ready")) or str(task_status.get("status") or "").upper() in {
        "SUCCESS",
        "FAILURE",
        "REVOKED",
    }


def _fetch_task_status(task_id: str, status_state_key: str) -> dict | None:
    try:
        task_status = api_get(f"/tasks/{task_id}")
    except requests.RequestException as exc:
        st.error(f"查詢失敗：{request_error_message(exc)}")
        return None
    st.session_state[status_state_key] = task_status
    return task_status


def _render_task_status_panel_controls(
    *,
    task_id: str,
    refresh_key: str,
    status_state_key: str,
    apply_result_key: str | None,
) -> dict | None:
    task_status = st.session_state.get(status_state_key)
    if not isinstance(task_status, dict) or task_status.get("task_id") != task_id:
        return None
    render_task_status(task_status)
    action_cols = st.columns(2)
    with action_cols[0]:
        if st.button("取消任務", key=f"{refresh_key}_cancel"):
            try:
                st.session_state[status_state_key] = api_task_post(f"/tasks/{task_id}/cancel", {})
                st.success("已送出取消要求。")
            except requests.RequestException as exc:
                st.error(f"取消失敗：{request_error_message(exc)}")
    with action_cols[1]:
        if st.button("重試任務", key=f"{refresh_key}_retry"):
            try:
                retry_response = api_task_post(f"/tasks/{task_id}/retry", {})
                st.session_state["last_data_task_id"] = retry_response.get("task_id") or task_id
                st.session_state[status_state_key] = retry_response
                st.success(f"已送出重試任務：{retry_response.get('task_id')}")
            except requests.RequestException as exc:
                st.error(f"重試失敗：{request_error_message(exc)}")
    result = (task_status or {}).get("result")
    if (
        apply_result_key
        and isinstance(result, dict)
        and isinstance(result.get("report"), dict)
        and st.button("載入本次分析結果", key=apply_result_key)
    ):
        st.session_state["last_analysis_result"] = result
        active_report_id = result.get("active_report_id") or result.get("report_id")
        if active_report_id:
            st.session_state["pending_selected_report_id"] = int(active_report_id)
        st.rerun()
    return task_status


def render_task_status_panel(
    *,
    task_id: str,
    refresh_key: str,
    apply_result_key: str | None = None,
    auto_refresh_seconds: int = 5,
) -> dict | None:
    if not task_id:
        st.warning("請輸入 task id。")
        return None
    status_state_key = f"{refresh_key}_status"
    task_status = st.session_state.get(status_state_key)
    if isinstance(task_status, dict) and task_status.get("task_id") != task_id:
        task_status = None
        st.session_state.pop(status_state_key, None)
    control_cols = st.columns([1, 1])
    with control_cols[0]:
        if st.button("刷新狀態", key=refresh_key):
            task_status = _fetch_task_status(task_id, status_state_key)
            if task_status is None:
                return None
    with control_cols[1]:
        auto_refresh = st.toggle(
            "自動刷新",
            value=not _task_status_ready(task_status),
            key=f"{refresh_key}_auto_refresh",
        )
    if not isinstance(task_status, dict):
        task_status = _fetch_task_status(task_id, status_state_key)
    fragment_factory = getattr(st, "fragment", None)
    if auto_refresh and not _task_status_ready(task_status) and callable(fragment_factory):
        interval = max(1, int(auto_refresh_seconds or 5))

        @fragment_factory(run_every=f"{interval}s")
        def _auto_task_status_panel() -> dict | None:
            current_status = st.session_state.get(status_state_key)
            if not _task_status_ready(current_status if isinstance(current_status, dict) else None):
                _fetch_task_status(task_id, status_state_key)
            return _render_task_status_panel_controls(
                task_id=task_id,
                refresh_key=refresh_key,
                status_state_key=status_state_key,
                apply_result_key=apply_result_key,
            )

        return _auto_task_status_panel()
    if auto_refresh and not callable(fragment_factory):
        st.caption("目前 Streamlit 版本不支援片段式自動刷新；請使用手動刷新。")
    return _render_task_status_panel_controls(
        task_id=task_id,
        refresh_key=refresh_key,
        status_state_key=status_state_key,
        apply_result_key=apply_result_key,
    )
