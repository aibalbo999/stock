from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, time, timedelta
from html import escape
from typing import Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

from app.core.config import get_settings
from app.core.time import today_taipei
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    filing_quality_score,
    filing_source_tier,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.status import db_status
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest
from app.rag.vector_store import VectorStore
from app.services.entity_mapping import EntityMapper
from app.services.ingestion import IngestionPipeline
from app.services.persistence import (
    AnalysisRunRepository,
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    NewsRepository,
    ReportRepository,
    ValuationMetricRepository,
)
from app.services.report_generator import ReportGenerator
from app.services.report_quality import (
    attach_quality_gate_to_report,
    build_quality_gate_for_request,
    parse_quality_gate_from_markdown,
)
from app.services.schedule_config import ScheduleConfig, ScheduleConfigStore
from app.services.service_status import service_status
from app.services.candidate_confidence import format_confidence_score
from app.services.whitelist import SupplyChainWhitelist

st.set_page_config(page_title="台股 AI 產業鏈分析", layout="wide")
init_db()

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');
    :root {
        --stock-primary: #6366f1;
        --stock-accent: #10b981;
        --stock-accent-soft: rgba(16, 185, 129, 0.15);
        --stock-info: #3b82f6;
        --stock-info-soft: rgba(59, 130, 246, 0.15);
        --stock-bg: #0f172a;
        --stock-surface: rgba(30, 41, 59, 0.6);
        --stock-surface-alt: rgba(15, 23, 42, 0.6);
        --stock-text: #f8fafc;
        --stock-muted: #94a3b8;
        --stock-border: rgba(255, 255, 255, 0.1);
        --stock-danger: #ef4444;
        --stock-danger-soft: rgba(239, 68, 68, 0.15);
        --stock-warning: #f59e0b;
        --stock-warning-soft: rgba(245, 158, 11, 0.15);
        --stock-focus: #8b5cf6;
    }
    html, body, [class*="css"] {
        font-family: "Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
        color: var(--stock-text);
    }
    /* Hide Streamlit header/footer for cleaner app-like feel */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container {
        padding-top: 1.1rem;
        padding-bottom: 3rem;
        max-width: 1240px;
    }
    h1, h2, h3 {
        letter-spacing: -0.02em;
        color: var(--stock-text);
    }
    h1 {
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
        background: linear-gradient(to right, #f8fafc, #818cf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    div[data-testid="stMetric"] {
        background: var(--stock-surface);
        border: 1px solid var(--stock-border);
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
        border-color: rgba(255, 255, 255, 0.2);
    }
    div[data-testid="stMetric"] label {
        color: var(--stock-muted) !important;
    }
    div[data-testid="stMetric"] div {
        color: var(--stock-text) !important;
    }
    div[data-testid="stForm"] {
        background: var(--stock-surface);
        border: 1px solid var(--stock-border);
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
    }
    div.stButton > button,
    div.stDownloadButton > button {
        min-height: 48px;
        border-radius: 12px;
        font-weight: 600;
        letter-spacing: 0.5px;
        background: linear-gradient(135deg, var(--stock-primary), var(--stock-focus));
        color: white;
        border: none;
        box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    div.stButton > button:hover,
    div.stDownloadButton > button:hover {
        box-shadow: 0 6px 20px rgba(99, 102, 241, 0.6);
        transform: translateY(-2px);
    }
    div.stButton > button:active,
    div.stDownloadButton > button:active {
        transform: translateY(1px);
        box-shadow: 0 2px 10px rgba(99, 102, 241, 0.4);
    }
    div[data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(15, 23, 42, 0.4);
        border: 1px solid var(--stock-border);
        border-radius: 12px;
        padding: 6px;
        backdrop-filter: blur(8px);
    }
    div[data-baseweb="tab"] {
        min-height: 44px;
        border-radius: 8px;
        padding-left: 18px;
        padding-right: 18px;
        color: var(--stock-muted);
        transition: all 0.2s ease;
    }
    div[data-baseweb="tab"]:hover {
        color: var(--stock-text);
    }
    div[data-baseweb="tab"][aria-selected="true"] {
        background: rgba(255, 255, 255, 0.1);
        color: var(--stock-text);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    .stock-hero {
        background: var(--stock-surface);
        border: 1px solid var(--stock-border);
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 20px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        display: grid;
        grid-template-columns: minmax(0, 1.7fr) minmax(260px, 0.9fr);
        gap: 20px;
        align-items: center;
        position: relative;
        overflow: hidden;
    }
    .stock-hero::before {
        content: '';
        position: absolute;
        top: -50%;
        left: -50%;
        width: 200%;
        height: 200%;
        background: radial-gradient(circle, rgba(99, 102, 241, 0.1) 0%, transparent 50%);
        pointer-events: none;
    }
    .stock-kicker {
        color: var(--stock-accent);
        font-weight: 700;
        margin-bottom: 6px;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-size: 0.85rem;
    }
    .stock-subtitle {
        color: var(--stock-muted);
        font-size: 1.05rem;
        line-height: 1.6;
        max-width: 720px;
    }
    .hero-actions {
        display: grid;
        gap: 10px;
    }
    .hero-pill {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid var(--stock-border);
        border-radius: 10px;
        padding: 12px 16px;
        color: var(--stock-text);
        font-size: 0.92rem;
        display: flex;
        align-items: center;
        backdrop-filter: blur(4px);
        transition: background 0.2s;
    }
    .hero-pill:hover {
        background: rgba(255, 255, 255, 0.1);
    }
    .section-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        gap: 16px;
        margin: 24px 0 12px;
    }
    .section-title {
        font-size: 1.15rem;
        font-weight: 600;
        color: var(--stock-text);
        border-left: 3px solid var(--stock-focus);
        padding-left: 8px;
    }
    .section-note {
        color: var(--stock-muted);
        font-size: 0.9rem;
        line-height: 1.5;
    }
    .compact-note {
        color: var(--stock-muted);
        font-size: 0.9rem;
        margin-top: -4px;
        margin-bottom: 8px;
    }
    .result-shell {
        background: var(--stock-surface);
        border: 1px solid var(--stock-border);
        border-radius: 12px;
        padding: 16px;
        margin-top: 14px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        backdrop-filter: blur(12px);
    }
    .status-supported {
        color: var(--stock-accent);
        font-weight: 700;
        text-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
    }
    .status-pending {
        color: var(--stock-warning);
        font-weight: 700;
        text-shadow: 0 0 10px rgba(245, 158, 11, 0.3);
    }
    /* Streamlit specific elements */
    [data-testid="stExpander"] {
        background: var(--stock-surface) !important;
        border: 1px solid var(--stock-border) !important;
        border-radius: 12px !important;
        backdrop-filter: blur(8px);
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--stock-border);
        border-radius: 12px;
        overflow: hidden;
    }
    @media (max-width: 640px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }
        h1 {
            font-size: 1.75rem;
        }
        .stock-hero {
            padding: 18px;
            grid-template-columns: 1fr;
        }
    }
    @media (prefers-reduced-motion: reduce) {
        * {
            transition: none !important;
            animation: none !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

API_BASE_URL = get_settings().api_base_url.rstrip("/")


def api_post(path: str, payload: dict) -> dict:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=900)
    response.raise_for_status()
    return response.json()


def api_get(path: str) -> dict:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


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
        line = line.lstrip("-0123456789. ")
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


def detail_html(markdown: str, title: str, heading: str) -> str:
    items = markdown_items(markdown, heading, limit=4)
    if not items:
        return ""
    body = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<details><summary>{escape(title)}</summary><ul>{body}</ul></details>"


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
    rows = markdown_table_rows(markdown, "個股比較矩陣", limit=8)
    if not rows:
        return ""
    cards = []
    action_count = 0
    watch_count = 0
    risk_count = 0
    for row in rows:
        stock = escape(row[0]) if len(row) > 0 else "-"
        decision_raw = row[1] if len(row) > 1 else "-"
        decision = escape(decision_raw)
        upside = escape(row[2]) if len(row) > 2 else "-"
        downside_raw = row[3] if len(row) > 3 else "-"
        downside = escape(downside_raw)
        valuation_raw = row[4] if len(row) > 4 else "-"
        valuation = escape(valuation_raw)
        confidence = escape(row[5]) if len(row) > 5 else "-"
        reminder = escape(row[6]) if len(row) > 6 else ""
        decision_class = decision_badge_class(decision_raw)
        valuation_class = valuation_badge_class(valuation_raw)
        downside_class = downside_badge_class(downside_raw)
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
                <div><span>升值</span><strong>{upside}</strong></div>
                <div class="{downside_class}"><span>降值</span><strong>{downside}</strong></div>
                <div class="{valuation_class}"><span>估值</span><strong>{valuation}</strong></div>
                <div><span>信心</span><strong>{confidence}</strong></div>
              </div>
            </article>
            """
        )
    summary = (
        f"<div class='matrix-summary'>"
        f"<span>可研究 {action_count}</span>"
        f"<span>觀察 {watch_count}</span>"
        f"<span>風險 {risk_count}</span>"
        f"</div>"
    )
    return summary + "".join(cards)


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
        }
        for candidate in candidates:
            evidence_sources = candidate.get("evidence_sources") or []
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
                    f"{int(candidate.get('evidence_count') or 0)} 篇 / {int(candidate.get('evidence_source_count') or 0)} 來源",
                    candidate.get("validation_reason") or "",
                    candidate.get("next_action") or "",
                    source_summary,
                    f"{candidate.get('evidence_confidence_label') or '未評分'} {candidate.get('evidence_confidence_score', '-')}",
                ]
            )
    else:
        rows = markdown_table_rows_by_header(markdown, "候選公司審計", "股票", limit=30)
    if not rows:
        return ""

    supported = [row for row in rows if len(row) > 2 and "正式分析" in row[2]]
    weak = [row for row in rows if len(row) > 2 and "弱證據" in row[2]]
    needs = [row for row in rows if len(row) > 2 and "待補" in row[2]]
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
        f"<span>正式分析 {len(supported)}</span>"
        f"<span>弱證據 {len(weak)}</span>"
        f"<span>待補證據 {len(needs)}</span>"
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
        items.append(f"<li><strong>阻擋：</strong>{escape(str(blocker))}</li>")
    for warning in warnings:
        items.append(f"<li><strong>警示：</strong>{escape(str(warning))}</li>")
    for observation in observations:
        items.append(f"<li><strong>觀察：</strong>{escape(str(observation))}</li>")
    action_items = "".join(f"<li>{escape(str(action))}</li>" for action in actions)
    action_html = (
        "<div class='quality-actions'><strong>建議補強</strong><ul>" + action_items + "</ul></div>"
        if action_items
        else ""
    )
    issue_html = "<ul>" + "".join(items) + "</ul>" if items else ""
    return f"<section class='panel quality-issues'><h2>品質警示</h2>{issue_html}{action_html}</section>"


def metric_percent(value: object) -> str:
    return "未評估" if value is None else f"{float(value or 0):.0%}"


def metric_int(value: object) -> str:
    return "未評估" if value is None else str(value)


def metric_number(value: object) -> str:
    if value is None:
        return "未評估"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def confidence_label(value: object) -> str:
    return format_confidence_score(float(value)) if value is not None else "未評估"


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
    report_id = result.get("report_id") if result else "-"
    promoted = len(result.get("promoted_tickers", [])) if result else metrics.get("promoted_count", "-")
    candidate_count = len(result.get("candidate_whitelist", [])) if result else "-"
    source_count = metrics.get("dynamic_source_count", 0)
    publisher_count = metric_int(metrics.get("source_unique_publishers"))
    timestamp_coverage = metric_percent(metrics.get("source_timestamp_coverage"))
    recent_coverage = metric_percent(metrics.get("source_recent_coverage"))
    leading_signal_coverage = metric_percent(metrics.get("leading_signal_coverage"))
    confidence_min = confidence_label(metrics.get("formal_confidence_min"))

    summary_items = markdown_items(markdown, "一頁摘要", limit=3)
    action_items = markdown_items(markdown, "下一步行動", limit=3)
    guard_items = markdown_items(markdown, "投資行動限制", limit=3)
    investment_rows = markdown_table_rows(markdown, "投資建議", limit=6)
    comparison_html = comparison_matrix_html(markdown)
    follow_up_html = follow_up_tasks_html(markdown)
    audit_html = candidate_audit_html(markdown, result)
    final_items = markdown_items(markdown, "二次綜合篩選", limit=3)

    summary_html = "".join(f"<li>{escape(item)}</li>" for item in summary_items) or "<li>目前無足夠數據判斷。</li>"
    action_html = "".join(f"<li>{escape(item)}</li>" for item in action_items) or "<li>先補資料後再重新分析。</li>"
    guard_html = "".join(f"<li>{escape(item)}</li>" for item in guard_items)
    cards = []
    for row in investment_rows:
        ticker = escape(row[0]) if len(row) > 0 else "-"
        decision = escape(row[1]) if len(row) > 1 else "-"
        reason = escape(row[2]) if len(row) > 2 else ""
        cards.append(
            f"""
            <article class="stock-card">
              <div>
                <div class="ticker">{ticker}</div>
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
            detail_html(markdown, "資金控管", "資金控管建議"),
            company_analysis_html(markdown),
            detail_html(markdown, "主要風險", "主要風險與瓶頸"),
            detail_html(markdown, "資料完整度", "資料完整度"),
            detail_html(markdown, "來源覆蓋", "來源覆蓋"),
            detail_html(markdown, "評分明細", "評分明細"),
        ]
    )
    return f"""
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<style>
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:#182230; background:#F4F7FB; }}
  .report {{ max-width:1040px; margin:0 auto; padding:18px 4px 30px; }}
  .hero {{ background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 100%); border:1px solid #D7DEE8; border-radius:8px; padding:20px; box-shadow:0 8px 22px rgba(32,48,71,0.06); }}
  .kicker {{ color:#0E9F6E; font-weight:700; font-size:14px; margin-bottom:6px; }}
  h1 {{ font-size:28px; line-height:1.25; margin:0 0 10px; }}
  h2 {{ font-size:18px; margin:22px 0 10px; }}
  .muted {{ color:#667085; }}
  .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:14px; }}
  .trust-grid {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; margin-top:10px; }}
  .metric {{ background:#FFFFFF; border:1px solid #D7DEE8; border-radius:8px; padding:14px; }}
  .metric span {{ display:block; color:#667085; font-size:13px; }}
  .metric strong {{ display:block; margin-top:4px; font-size:20px; }}
  .status {{ display:inline-block; border-radius:999px; padding:6px 10px; font-size:13px; font-weight:700; }}
  .ready {{ background:#E4F8F0; color:#087443; }}
  .caution {{ background:#FFF4DA; color:#8A5A12; }}
  .insufficient {{ background:#FDEAE7; color:#B42318; }}
  .unknown {{ background:#E8EEF6; color:#344054; }}
  .panel {{ background:#FFFFFF; border:1px solid #D7DEE8; border-radius:8px; padding:16px; margin-top:12px; }}
  .quality-issues {{ border-color:#F5C97B; background:#FFFCF2; }}
  .quality-issues strong {{ color:#8A5A12; }}
  .quality-actions {{ margin-top:12px; border-top:1px solid #F5C97B; padding-top:12px; }}
  .quality-actions strong {{ display:block; margin-bottom:2px; }}
  ul {{ margin:8px 0 0; padding-left:20px; }}
  li {{ margin:7px 0; line-height:1.55; }}
  .stock-list {{ display:grid; gap:10px; }}
  .stock-card {{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; border:1px solid #D7DEE8; border-radius:8px; padding:14px; background:#FFFFFF; }}
  .task-card {{ display:flex; justify-content:space-between; gap:14px; border:1px solid #D7DEE8; border-radius:8px; padding:14px; background:#F9FBFD; margin:8px 0; }}
  .task-meta {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; align-content:flex-start; min-width:220px; }}
  .task-meta span {{ background:#E7F0FF; color:#1D4ED8; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:700; }}
  .audit-summary {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }}
  .audit-summary span {{ background:#F4F7FB; border:1px solid #D7DEE8; border-radius:999px; padding:6px 10px; font-size:13px; color:#344054; font-weight:700; }}
  .audit-card {{ display:flex; justify-content:space-between; gap:14px; border:1px solid #D7DEE8; border-radius:8px; padding:14px; background:#FFFFFF; margin:8px 0; }}
  .audit-card.audit-supported {{ border-left:4px solid #0E9F6E; }}
  .audit-card.audit-weak {{ border-left:4px solid #F59E0B; }}
  .audit-card.audit-needs {{ border-left:4px solid #667085; }}
  .audit-reason {{ margin-top:8px; color:#344054; font-size:13px; line-height:1.45; }}
  .audit-next {{ margin-top:5px; color:#53657D; font-size:13px; line-height:1.45; }}
  .audit-source {{ margin-top:8px; color:#667085; font-size:12px; line-height:1.45; border-top:1px solid #EAECF0; padding-top:8px; }}
  .audit-meta {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; align-content:flex-start; min-width:180px; }}
  .audit-meta span {{ background:#F4F7FB; color:#344054; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:700; }}
  .matrix-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
  .matrix-summary {{ grid-column:1/-1; display:flex; gap:8px; flex-wrap:wrap; margin-bottom:2px; }}
  .matrix-summary span {{ background:#F4F7FB; border:1px solid #D7DEE8; border-radius:999px; padding:6px 10px; font-size:13px; color:#344054; font-weight:700; }}
  .matrix-card {{ border:1px solid #D7DEE8; border-radius:8px; padding:14px; background:#FFFFFF; }}
  .matrix-card.decision-action {{ border-left:4px solid #0E9F6E; }}
  .matrix-card.decision-watch {{ border-left:4px solid #F59E0B; }}
  .matrix-card.decision-risk {{ border-left:4px solid #D92D20; }}
  .matrix-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; }}
  .mini-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }}
  .mini-grid div {{ background:#F4F7FB; border-radius:8px; padding:8px; }}
  .mini-grid .valuation-high {{ background:#FFF4DA; }}
  .mini-grid .valuation-low {{ background:#E4F8F0; }}
  .mini-grid .risk-high {{ background:#FDEAE7; }}
  .mini-grid .risk-low {{ background:#E4F8F0; }}
  .mini-grid span {{ display:block; color:#667085; font-size:12px; }}
  .mini-grid strong {{ display:block; margin-top:3px; font-size:14px; }}
  .ticker {{ font-weight:800; margin-bottom:6px; }}
  .reason {{ color:#53657D; font-size:14px; line-height:1.5; }}
  .decision {{ white-space:nowrap; background:#E7F0FF; color:#1D4ED8; border-radius:999px; padding:6px 10px; font-weight:700; font-size:13px; }}
  .decision.decision-action {{ background:#E4F8F0; color:#087443; }}
  .decision.decision-watch {{ background:#FFF4DA; color:#8A5A12; }}
  .decision.decision-risk {{ background:#FDEAE7; color:#B42318; }}
  details {{ background:#F9FBFD; border:1px solid #D7DEE8; border-radius:8px; padding:12px 14px; margin:8px 0; }}
  summary {{ cursor:pointer; font-weight:700; }}
  .company-detail {{ background:#FFFFFF; margin:10px 0 0; }}
  .company-detail summary {{ color:#1D4ED8; }}
  @media (max-width:760px) {{ .grid,.trust-grid,.matrix-list {{ grid-template-columns:1fr; }} .stock-card,.task-card,.audit-card,.matrix-top {{ display:block; }} .decision,.task-meta,.audit-meta {{ display:inline-flex; margin-top:10px; justify-content:flex-start; min-width:0; }} }}
</style>
</head>
<body>
<main class="report">
  <section class="hero">
    <div class="kicker">AI 台股分析報告</div>
    <h1>先看能不能用，再看要不要研究</h1>
    <span class="status {status_class}">{escape(status_labels.get(status, status))}</span>
    <p class="muted">{escape(action_policy.get("label", "請先檢查資料品質與來源覆蓋。"))}</p>
    <div class="grid">
      <div class="metric"><span>報告</span><strong>#{escape(str(report_id))}</strong></div>
      <div class="metric"><span>可投入上限</span><strong>{escape(amount_label)}</strong></div>
      <div class="metric"><span>正式股票</span><strong>{escape(str(promoted))}</strong></div>
      <div class="metric"><span>候選清單</span><strong>{escape(str(candidate_count))}</strong></div>
    </div>
    <div class="trust-grid">
      <div class="metric"><span>來源篇數</span><strong>{escape(str(source_count))}</strong></div>
      <div class="metric"><span>來源家數</span><strong>{escape(publisher_count)}</strong></div>
      <div class="metric"><span>日期可查</span><strong>{escape(timestamp_coverage)}</strong></div>
      <div class="metric"><span>近期資料</span><strong>{escape(recent_coverage)}</strong></div>
      <div class="metric"><span>領先訊號</span><strong>{escape(leading_signal_coverage)}</strong></div>
      <div class="metric"><span>最低信心</span><strong>{escape(confidence_min)}</strong></div>
    </div>
  </section>
  {quality_html}
  <section class="panel"><h2>重點摘要</h2><ul>{summary_html}</ul></section>
  {"<section class='panel'><h2>投資行動限制</h2><ul>" + guard_html + "</ul></section>" if guard_html else ""}
  <section class="panel"><h2>下一步</h2><ul>{action_html}</ul></section>
  {"<section class='panel'><h2>候選公司審計</h2>" + audit_html + "</section>" if audit_html else ""}
  {"<section class='panel'><h2>系統會自動補強</h2>" + follow_up_html + "</section>" if follow_up_html else ""}
  {"<section class='panel'><h2>個股比較矩陣</h2><div class='matrix-list'>" + comparison_html + "</div></section>" if comparison_html else ""}
  <section class="panel"><h2>個股建議</h2><div class="stock-list">{investment_html}</div></section>
  {"<section class='panel'><h2>二次篩選</h2><ul>" + final_html + "</ul></section>" if final_html else ""}
  <section class="panel"><h2>展開看細節</h2>{details or "<p class='muted'>目前沒有更多細節。</p>"}</section>
</main>
</body>
</html>
"""


def candidate_revalidation_summary(result: dict) -> dict:
    revalidation = ((result.get("rerun_report") or {}).get("candidate_revalidation") or {})
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
    return {
        "changed": bool(revalidation.get("changed")),
        "total": len(candidates),
        "promoted_count": len(promoted) if promoted else len(supported),
        "weak_count": len(weak),
        "needs_evidence_count": len(needs),
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


def follow_up_result_message(result: dict, summary_text: str) -> tuple[str, str]:
    rerun = result.get("rerun_report") or {}
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
    rerun_actions = (result.get("rerun_report") or {}).get("next_actions") or []
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
    for blocker in (result.get("rerun_report") or {}).get("blockers") or []:
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
        f"報告證據上限：{audit.get('evidence_limit')}"
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
    cols[3].metric("可投入上限", f"{int(amount):,}" if amount is not None else "-")
    source_cols = st.columns(6)
    source_cols[0].metric("來源篇數", metrics.get("dynamic_source_count", 0))
    source_cols[1].metric("來源家數", metric_int(metrics.get("source_unique_publishers")))
    source_cols[2].metric("日期可查", metric_percent(metrics.get("source_timestamp_coverage")))
    source_cols[3].metric("近期資料", metric_percent(metrics.get("source_recent_coverage")))
    source_cols[4].metric("領先訊號", metric_percent(metrics.get("leading_signal_coverage")))
    source_cols[5].metric("最低信心", confidence_label(metrics.get("formal_confidence_min")))
    llm_status = metrics.get("llm_analysis_status")
    if llm_status:
        st.caption("模型補充分析：" + ("已啟用" if llm_status == "enabled" else "退回規則引擎"))
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


def render_follow_up_controls(report_id: int, markdown: str) -> None:
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
            key=f"followup_force_refresh_{report_id}",
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
        key=f"followup_purpose_{report_id}",
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
    has_executable_actions = bool(executable_actions or rows)
    if planned_actions and not executable_actions:
        st.caption("目前選擇的範圍沒有可執行任務。")
    elif executable_actions:
        selected_required = sum(1 for action in executable_actions if action.get("purpose") == "required")
        selected_tracking = sum(1 for action in executable_actions if action.get("purpose") == "tracking")
        st.caption(f"本次將執行：資料缺口補強 {selected_required} 項，追蹤更新 {selected_tracking} 項。")
    cols = st.columns([0.62, 0.38])
    rerun_report = cols[0].checkbox("完成後重新產生一份報告", value=True, key=f"followup_rerun_{report_id}")
    news_limit = cols[1].number_input(
        "補抓資料量",
        min_value=10,
        max_value=100,
        value=30,
        step=10,
        key=f"followup_news_limit_{report_id}",
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
        key=f"followup_run_{report_id}",
        disabled=not has_executable_actions,
    ):
        with st.spinner("正在補資料、重算訊號並更新報告..."):
            try:
                result = api_post(
                    f"/reports/{report_id}/follow-up/run",
                    {
                        "rerun_report": bool(rerun_report),
                        "news_limit": int(news_limit),
                        "purpose": selected_purpose,
                        "force_refresh": bool(force_refresh),
                    },
                )
                st.session_state["last_follow_up_result"] = result
                new_report = result.get("rerun_report") or {}
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
                revalidation = candidate_revalidation_summary(result)
                if revalidation["total"]:
                    changed_label = "清單已更新" if revalidation["changed"] else "清單無變化"
                    summary_text += (
                        f"，候選重新驗證：正式 {revalidation['promoted_count']} 檔、"
                        f"弱證據 {revalidation['weak_count']} 檔、待補 {revalidation['needs_evidence_count']} 檔"
                        f"（{changed_label}）"
                    )
                    if revalidation["document_count"]:
                        summary_text += (
                            f"，驗證文件 {revalidation['document_count']} 筆"
                            f"/查詢 {revalidation['document_query_count']} 組"
                        )
                    if revalidation["newly_promoted"]:
                        summary_text += "，新升格：" + "、".join(revalidation["newly_promoted"][:6])
                    if revalidation["no_longer_promoted"]:
                        summary_text += "，降回觀察：" + "、".join(revalidation["no_longer_promoted"][:6])
                message_level, message_text = follow_up_result_message(result, summary_text)
                if new_report.get("report_id"):
                    st.session_state["follow_up_flash"] = {
                        "level": message_level,
                        "message": message_text,
                        "result": result,
                    }
                    st.session_state["selected_report_id"] = int(new_report["report_id"])
                    st.rerun()
                elif new_report.get("status") == "skipped":
                    st.warning(message_text)
                else:
                    st.success(message_text)
                blocker_rows = follow_up_blocker_action_rows(result)
                if blocker_rows:
                    st.caption("重跑前需要處理")
                    st.dataframe(blocker_rows, width="stretch", hide_index=True)
            except requests.RequestException as exc:
                st.error(f"自動補強失敗：{exc}")


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


st.markdown(
    """
    <section class="stock-hero">
        <div>
            <div class="stock-kicker">AI 台股投資工作台</div>
            <h1>先判斷資料能不能用，再決定股票能不能研究</h1>
            <div class="stock-subtitle">
                從主題拆解、資料抓取、候選公司驗證到資金上限，集中在同一個工作流程完成。
            </div>
        </div>
        <div class="hero-actions">
            <div class="hero-pill">流程：主題分析 → 來源驗證 → 個股評估 → 投資行動限制</div>
            <div class="hero-pill">時間：Asia/Taipei，本日 {today}</div>
            <div class="hero-pill">原則：資料不足時自動降級為研究草稿</div>
        </div>
    </section>
    """.format(today=today_taipei().isoformat()),
    unsafe_allow_html=True,
)

tabs = st.tabs(["分析", "報告", "資料", "設定"])

with tabs[0]:
    render_section_header("建立一次分析", "預設使用 AI 拆解主題並抓取國內外資料；不確定時維持預設即可。")
    analysis_config_col, analysis_result_col = st.columns([0.36, 0.64], gap="large")
    with analysis_config_col:
        with st.form("analysis_form"):
            st.markdown("#### 分析設定")
            st.markdown(
                '<div class="compact-note">輸入主題，系統會自行拆解子題並建立候選股票。</div>',
                unsafe_allow_html=True,
            )
            topic = st.text_input("分析主題", value="AI 產業鏈")
            lookback_days = st.slider("新聞與市場資料回看天數", min_value=7, max_value=60, value=14)
            investor_capital = st.number_input(
                "可投入總資金",
                min_value=10000,
                max_value=100000000,
                value=1000000,
                step=10000,
            )
            profile_label = st.selectbox(
                "投資人設定",
                options=["新手保守", "一般穩健", "積極成長"],
                index=0,
            )
            profile_map = {"新手保守": "beginner", "一般穩健": "balanced", "積極成長": "aggressive"}
            investor_profile = profile_map[profile_label]
            beginner_mode = investor_profile == "beginner"

            st.markdown("#### 風險與資金")
            max_position_pct = st.slider("單檔上限", min_value=1, max_value=20, value=10, format="%d%%")
            cash_reserve_pct = st.slider("保留現金", min_value=10, max_value=80, value=30, format="%d%%")
            discovery_limit = st.slider("資料抓取強度", min_value=2, max_value=20, value=5)

            with st.expander("進階選項"):
                ai_discovery_mode = st.checkbox("由 AI 拆解主題與建立候選清單", value=True)
                deep_analysis = st.checkbox("深度分析（較慢，抓更多國際/本地來源）", value=True)
                include_international = st.checkbox("納入國際資料源", value=True)
                evidence_limit = st.slider(
                    "報告引用資料量",
                    min_value=40,
                    max_value=200,
                    value=120 if deep_analysis else 40,
                    step=20,
                )
                refresh_before_report = st.checkbox("手動模式產報告前刷新資料", value=False)
                tickers = st.multiselect(
                    "手動模式個股範圍",
                    options=sorted(SupplyChainWhitelist().allowed_tickers()),
                    default=[],
                )
                run_async = st.checkbox("稍後查看結果（背景執行）", value=False)

            run_sync = st.form_submit_button("執行分析", type="primary")

        if run_sync and not run_async:
            if ai_discovery_mode:
                with st.spinner("AI 正在拆解主題、抓取資料並產生二次篩選報告..."):
                    try:
                        result = api_post(
                            "/pipeline/run_discovered",
                            {
                                "topic": topic,
                                "limit_per_query": int(discovery_limit),
                                "lookback_days": int(lookback_days),
                                "evidence_limit": int(evidence_limit),
                                "deep_analysis": bool(deep_analysis),
                                "include_international": bool(include_international),
                                "investor_capital": int(investor_capital),
                                "beginner_mode": bool(beginner_mode),
                                "investor_profile": investor_profile,
                                "max_position_pct": float(max_position_pct) / 100,
                                "cash_reserve_pct": float(cash_reserve_pct) / 100,
                            },
                        )
                        st.session_state["last_analysis_result"] = result
                        st.success(f"已完成報告 #{result['report_id']}")
                    except requests.RequestException as exc:
                        st.error(f"AI 探索式流程失敗：{exc}")
            else:
                request = ReportRequest(
                    topic=topic,
                    tickers=tickers,
                    lookback_days=int(lookback_days),
                    evidence_limit=int(evidence_limit),
                    investor_capital=int(investor_capital),
                    beginner_mode=bool(beginner_mode),
                    investor_profile=investor_profile,
                    max_position_pct=float(max_position_pct) / 100,
                    cash_reserve_pct=float(cash_reserve_pct) / 100,
                )
                with session_scope() as session:
                    run = AnalysisRunRepository(session).start("streamlit_sync", request.model_dump(mode="json"))
                    run_id = run.id
                ingestion_summary = {}
                if refresh_before_report:
                    with st.spinner("正在刷新新聞與市場資料..."):
                        ingestion_summary = asyncio.run(IngestionPipeline().pre_report_refresh(request))
                    st.json(ingestion_summary)
                try:
                    generator = ReportGenerator()
                    response = generator.generate(request)
                    refreshed_count = (ingestion_summary.get("news") or {}).get("count")
                    source_count = (
                        max(refreshed_count, len(generator.last_evidence_documents))
                        if refreshed_count is not None
                        else None
                    )
                    quality_gate = build_quality_gate_for_request(
                        request,
                        documents=generator.last_evidence_documents,
                        source_count=source_count,
                        llm_result=getattr(generator, "last_llm_result", None),
                    )
                    response = attach_quality_gate_to_report(response, quality_gate)
                    with session_scope() as session:
                        report = ReportRepository(session).create(request, response)
                        AnalysisRunRepository(session).update_payload(
                            run_id,
                            {
                                "request": request.model_dump(mode="json"),
                                "ingestion": ingestion_summary,
                                "quality_gate": quality_gate,
                                "evidence_count": len(generator.last_evidence_documents),
                            },
                        )
                        AnalysisRunRepository(session).mark_success(run_id, report.id)
                    st.session_state["last_analysis_result"] = {
                        "run_id": run_id,
                        "report_id": report.id,
                        "candidate_whitelist": [],
                        "promoted_tickers": tickers,
                        "quality_gate": quality_gate,
                        "report": response.model_dump(mode="json"),
                    }
                    st.success(f"已完成報告 #{report.id}")
                except Exception as exc:
                    with session_scope() as session:
                        AnalysisRunRepository(session).mark_failed(run_id, str(exc))
                    st.error(str(exc))

        if run_sync and run_async:
            if ai_discovery_mode:
                st.warning("背景執行目前只支援手動個股範圍；AI 拆解主題請取消背景執行後直接分析。")
            elif not tickers:
                st.warning("背景執行請至少選擇一檔白名單股票。")
            else:
                payload = {
                    "topic": topic,
                    "tickers": tickers,
                    "lookback_days": int(lookback_days),
                    "evidence_limit": int(evidence_limit),
                    "investor_capital": int(investor_capital),
                    "beginner_mode": bool(beginner_mode),
                    "investor_profile": investor_profile,
                    "max_position_pct": float(max_position_pct) / 100,
                    "cash_reserve_pct": float(cash_reserve_pct) / 100,
                }
                try:
                    task_response = api_post("/reports/generate_async", payload)
                    st.session_state["last_async_task_id"] = task_response["task_id"]
                    st.success(f"已送出非同步任務：{task_response['task_id']}")
                except requests.RequestException as exc:
                    st.error(f"非同步任務送出失敗：{exc}")

        with st.expander("疑難排解：查詢背景分析"):
            last_task_id = st.session_state.get("last_async_task_id")
            task_id = st.text_input("背景分析編號", value=last_task_id or "")
            task_status_col, task_run_col = st.columns(2)
            with task_status_col:
                refresh_task_status = st.button("刷新狀態")
            with task_run_col:
                lookup_task_run = st.button("查詢紀錄")
            if refresh_task_status or lookup_task_run:
                if not task_id:
                    st.warning("請輸入 task id。")
                elif refresh_task_status:
                    try:
                        render_task_status(api_get(f"/tasks/{task_id}"))
                    except requests.RequestException as exc:
                        st.error(f"查詢失敗：{exc}")
                else:
                    try:
                        st.json(api_get(f"/tasks/{task_id}/run"))
                    except requests.HTTPError as exc:
                        if exc.response.status_code == 404:
                            st.info("尚未找到對應紀錄；任務剛送出時可能需要等待。")
                        else:
                            st.error(f"查詢失敗：{exc}")
                    except requests.RequestException as exc:
                        st.error(f"查詢失敗：{exc}")

    with analysis_result_col:
        result = st.session_state.get("last_analysis_result")
        if result:
            report_markdown = result["report"]["markdown"]
            metric_cols = st.columns(4)
            metric_cols[0].metric("報告", f"#{result['report_id']}")
            metric_cols[1].metric("正式分析股票", len(result.get("promoted_tickers", [])))
            metric_cols[2].metric("候選清單", len(result.get("candidate_whitelist", [])))
            metric_cols[3].metric("資金上限", f"{int(investor_capital):,}")
            render_market_errors(result)

            render_section_header("本次分析結果", "先看重點報告；資料細節只在需要查核時展開。")
            result_tabs = st.tabs(["重點報告", "資料說明"])
            with result_tabs[0]:
                st.download_button(
                    "下載 HTML 報告",
                    data=report_html(report_markdown, result),
                    file_name=f"report_{result['report_id']}.html",
                    mime="text/html",
                )
                render_reader_report(report_markdown, result)
            with result_tabs[1]:
                render_quality_gate(result)
                render_company_data_audit(int(result["report_id"]))
                render_follow_up_controls(int(result["report_id"]), report_markdown)
                with st.expander("資料來源概況"):
                    render_source_audit(result)
                if result.get("candidate_whitelist"):
                    st.markdown("**候選清單驗證**")
                    st.dataframe(candidate_rows(result["candidate_whitelist"]), width="stretch", hide_index=True)
                with st.expander("進階：原始報告文字"):
                    st.markdown(report_markdown)
        else:
            st.markdown(
                """
                <div class="result-shell">
                    <div class="section-title">等待分析結果</div>
                    <div class="section-note">
                        左側完成設定後執行分析。結果會在這裡以 HTML 卡片報告呈現，資料來源與完整文字會收在次要區塊。
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

with tabs[1]:
    render_section_header("報告中心", "查看已產出的 HTML 報告與下載檔案。")
    render_follow_up_flash()
    report_nav_col, report_preview_col = st.columns([0.30, 0.70], gap="large")
    with session_scope() as session:
        reports = ReportRepository(session).latest(20)
        report_options = [
            {
                "id": report.id,
                "label": f"{report.generated_at:%Y-%m-%d %H:%M}｜{report.title}",
            }
            for report in reports
        ]
    with report_nav_col:
        if report_options:
            report_ids = [report["id"] for report in report_options]
            if st.session_state.get("selected_report_id") not in report_ids:
                st.session_state["selected_report_id"] = report_ids[0]
            selected_id = st.selectbox(
                "選擇報告",
                options=report_ids,
                key="selected_report_id",
                format_func=lambda report_id: next(
                    report["label"] for report in report_options if report["id"] == report_id
                ),
            )
        else:
            selected_id = None
            st.info("尚無歷史報告。")

        report_markdown = None
        report_title = "report"
        history_result = None
        if selected_id:
            try:
                report_payload = api_get(f"/reports/{int(selected_id)}")
                report_markdown = report_payload.get("markdown")
                report_title = report_payload.get("title") or "report"
                history_result = {
                    "report_id": selected_id,
                    "quality_gate": report_payload.get("quality_gate") or parse_quality_gate_from_markdown(report_markdown or ""),
                    "candidate_whitelist": report_payload.get("candidate_whitelist") or [],
                    "candidate_audit": report_payload.get("candidate_audit") or {},
                }
            except requests.RequestException:
                with session_scope() as session:
                    report = ReportRepository(session).get(int(selected_id))
                    report_markdown = report.markdown if report else None
                    report_title = report.title if report else "report"
            if report_markdown:
                history_result = history_result or {
                    "report_id": selected_id,
                    "quality_gate": parse_quality_gate_from_markdown(report_markdown),
                }
        if selected_id and report_markdown:
            history_html = report_html(report_markdown, history_result)
            st.download_button(
                "下載 HTML",
                data=history_html,
                file_name=f"report_{selected_id}.html",
                mime="text/html",
            )
            with st.expander("進階"):
                st.download_button(
                    "下載 Markdown",
                    data=report_markdown,
                    file_name=f"report_{selected_id}.md",
                    mime="text/markdown",
                )
                if st.button("刪除此報告"):
                    with session_scope() as session:
                        ReportRepository(session).delete(int(selected_id))
                    st.success(f"已刪除報告 #{selected_id}｜{report_title}")

    with report_preview_col:
        if selected_id and report_markdown:
            history_tabs = st.tabs(["重點報告", "資料說明", "完整文字"])
            with history_tabs[0]:
                render_reader_report(report_markdown, history_result)
            with history_tabs[1]:
                if history_result:
                    render_quality_gate(history_result)
                    render_company_data_audit(int(selected_id))
                    render_follow_up_controls(int(selected_id), report_markdown)
                    candidates = history_result.get("candidate_whitelist") or []
                    if candidates:
                        with st.expander("候選公司審計"):
                            st.dataframe(candidate_rows(candidates), width="stretch", hide_index=True)
                else:
                    st.info("此份報告尚無可解析的品質門檻。")
            with history_tabs[2]:
                st.markdown(report_markdown)
        else:
            st.markdown(
                """
                <div class="result-shell">
                    <div class="section-title">尚未選擇報告</div>
                    <div class="section-note">左側選擇一份歷史報告後，這裡會顯示 HTML 重點版。</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.expander("疑難排解：分析紀錄"):
        render_section_header("分析紀錄", "一般閱讀報告不需要查看；只有查錯或追蹤背景分析時使用。")
        with session_scope() as session:
            run_rows = []
            for run in AnalysisRunRepository(session).latest(20):
                payload = parse_json_object(run.payload_json)
                run_rows.append(
                    {
                        "id": run.id,
                        "source": run.source,
                        "status": run.status,
                        "report_id": run.report_id,
                        "celery_task_id": payload.get("celery_task_id"),
                        "started_at": run.started_at.isoformat(timespec="seconds"),
                        "finished_at": run.finished_at.isoformat(timespec="seconds")
                        if run.finished_at
                        else None,
                        "error": run.error,
                    }
                )
        if run_rows:
            st.dataframe(
                run_rows,
                width="stretch",
                hide_index=True,
            )
            selected_run_id = st.selectbox(
                "查看 run",
                options=[row["id"] for row in run_rows],
                format_func=lambda run_id: f"紀錄 #{run_id}",
            )
            with session_scope() as session:
                selected_run = AnalysisRunRepository(session).get(int(selected_run_id))
                selected_run_payload = selected_run.payload_json if selected_run else "{}"
                selected_run_error = selected_run.error if selected_run else None
            selected_payload = parse_json_object(selected_run_payload)
            selected_task_id = selected_payload.get("celery_task_id")
            with st.expander("原始紀錄內容"):
                try:
                    st.json(json.loads(selected_run_payload))
                except json.JSONDecodeError:
                    st.code(selected_run_payload)
            if selected_task_id and st.button("查詢背景任務狀態"):
                try:
                    st.json(api_get(f"/tasks/{selected_task_id}"))
                except requests.RequestException as exc:
                    st.error(f"查詢失敗：{exc}")
            if selected_run_error:
                st.error(selected_run_error)
            if st.button("刪除此分析紀錄"):
                with session_scope() as session:
                    AnalysisRunRepository(session).delete(int(selected_run_id))
                st.success(f"已刪除分析紀錄 #{selected_run_id}")
        else:
            st.info("尚無任務執行紀錄。")

with tabs[2]:
    render_section_header("市場資料", "刷新股價、五年財報與估值資料；這些資料會影響品質門檻與投資行動限制。")
    whitelist = SupplyChainWhitelist()
    allowed_tickers = sorted(whitelist.allowed_tickers())
    status_snapshot = db_status()
    table_counts = status_snapshot.get("tables", {})
    count_cols = st.columns(5)
    count_cols[0].metric("股價快取", table_counts.get("stock_price_snapshots", {}).get("count") or 0)
    count_cols[1].metric("月營收快取", table_counts.get("monthly_revenue_snapshots", {}).get("count") or 0)
    count_cols[2].metric("財報三表快取", table_counts.get("financial_metric_snapshots", {}).get("count") or 0)
    count_cols[3].metric("估值快取", table_counts.get("valuation_metric_snapshots", {}).get("count") or 0)
    count_cols[4].metric("公司文件", table_counts.get("company_filings", {}).get("count") or 0)

    selected_market_tickers = st.multiselect(
        "刷新個股",
        options=allowed_tickers,
        default=["2330"] if "2330" in allowed_tickers else [],
    )
    col_start, col_end = st.columns(2)
    with col_start:
        market_start = st.date_input("起始日期", value=today_taipei().replace(day=1), key="market_start")
    with col_end:
        market_end = st.date_input("結束日期", value=today_taipei(), key="market_end")

    refresh_cols = st.columns(4)
    refresh_price = refresh_cols[0].button("刷新股價", type="primary")
    refresh_financials = refresh_cols[1].button("刷新 5 年財報")
    refresh_valuations = refresh_cols[2].button("刷新估值")
    refresh_filings = refresh_cols[3].button("補抓公司文件")

    if refresh_price:
        if market_start > market_end:
            st.error("起始日期不可晚於結束日期。")
        elif not selected_market_tickers:
            st.warning("請至少選擇一檔白名單股票。")
        else:
            with st.spinner("正在抓取 FinMind 資料..."):
                snapshots, errors = asyncio.run(
                    MarketDataClient().get_latest_snapshots_with_errors(
                        selected_market_tickers,
                        market_start,
                        market_end,
                    )
                )
                with session_scope() as session:
                    MarketRepository(session).upsert_snapshots(snapshots)
            st.success(f"已更新 {len(snapshots)} 筆市場資料。")
            if errors:
                render_market_errors({"market_errors": [error.model_dump() for error in errors]})

    if refresh_financials:
        if not selected_market_tickers:
            st.warning("請至少選擇一檔白名單股票。")
        else:
            with st.spinner("正在抓取 FinMind 財報三表..."):
                result = asyncio.run(
                    IngestionPipeline().refresh_financial_metrics(
                        selected_market_tickers,
                        market_end - timedelta(days=365 * 6),
                        market_end,
                    )
                )
            st.success(f"已更新 {result['stored_count']} 筆財報科目。")
            if result["errors"]:
                st.warning(result["errors"])

    if refresh_valuations:
        if market_start > market_end:
            st.error("起始日期不可晚於結束日期。")
        elif not selected_market_tickers:
            st.warning("請至少選擇一檔白名單股票。")
        else:
            with st.spinner("正在抓取 FinMind 估值資料..."):
                result = asyncio.run(
                    IngestionPipeline().refresh_valuations(
                        selected_market_tickers,
                        market_start,
                        market_end,
                    )
                )
            st.success(f"已更新 {len(result['stored'])} 筆估值資料。")
            if result["errors"]:
                st.warning(result["errors"])

    if refresh_filings:
        if not selected_market_tickers:
            st.warning("請至少選擇一檔白名單股票。")
        else:
            with st.spinner("正在搜尋官方/MOPS/IR 公司文件..."):
                result = asyncio.run(
                    IngestionPipeline().ingest_company_filings(
                        selected_market_tickers,
                        limit_per_query=3,
                    )
                )
            st.success(f"已新增或更新 {result['stored_count']} 筆公司文件線索。")
            gap_summary = result.get("gap_summary") or {}
            if gap_summary.get("recommendation"):
                st.info(gap_summary["recommendation"])
            per_ticker_results = result.get("per_ticker_results") or []
            if per_ticker_results:
                st.caption("公司文件補強狀態")
                st.dataframe(
                    [
                        {
                            "股票": row.get("ticker"),
                            "公司": row.get("company_name"),
                            "狀態": {
                                "sufficient": "足夠",
                                "retry_recommended": "可自動重試",
                                "broader_search_recommended": "需擴大搜尋",
                                "needs_manual_source": "需補文件",
                            }.get(row.get("status"), row.get("status")),
                            "已抓文件": row.get("stored_count", 0),
                            "搜尋嘗試": len(row.get("attempts") or []),
                            "缺必要文件": "、".join(row.get("missing_required_types") or []),
                            "缺建議文件": "、".join(row.get("missing_recommended_types") or []),
                            "下一步": row.get("next_step"),
                        }
                        for row in per_ticker_results
                    ],
                    width="stretch",
                    hide_index=True,
                )
            next_actions = result.get("next_actions") or []
            if next_actions:
                manual_tickers = [
                    action.get("ticker", "")
                    for action in next_actions
                    if action.get("action") == "manual_company_filing_import"
                ]
                retry_tickers = [
                    action.get("ticker", "")
                    for action in next_actions
                    if action.get("action") == "retry_company_filing_search"
                ]
                broaden_tickers = [
                    action.get("ticker", "")
                    for action in next_actions
                    if action.get("action") == "broaden_company_filing_search"
                ]
                if retry_tickers:
                    st.info("可稍後自動重試：" + "、".join(retry_tickers))
                if broaden_tickers:
                    st.info("需擴大官方搜尋：" + "、".join(broaden_tickers))
                if manual_tickers:
                    st.info("仍需人工補官方文件：" + "、".join(manual_tickers))
            plans = result.get("official_search_plans") or []
            if plans:
                st.caption("官方搜尋計畫")
                st.dataframe(
                    [
                        {
                            "股票": plan.get("ticker"),
                            "公司": plan.get("company_name"),
                            "查詢數": len(plan.get("queries") or []),
                            "官方入口": "、".join(
                                portal.get("name", "")
                                for portal in plan.get("official_portals") or []
                            ),
                            "查詢範例": (plan.get("queries") or [""])[0],
                        }
                        for plan in plans
                    ],
                    width="stretch",
                    hide_index=True,
                )
            if result["errors"]:
                st.warning(result["errors"])

    with session_scope() as session:
        cached_snapshots = MarketRepository(session).latest_by_tickers(allowed_tickers)
        cached_valuations = ValuationMetricRepository(session).latest_by_tickers(allowed_tickers)
        cached_filings = CompanyFilingRepository(session).latest_by_tickers(allowed_tickers, limit_per_ticker=2)
        cached_financial_count = len(FinancialMetricRepository(session).by_tickers(allowed_tickers))
    if cached_snapshots:
        st.caption("最新股價快取")
        st.dataframe(
            [
                {
                    "ticker": snapshot.ticker,
                    "trade_date": snapshot.trade_date.isoformat(),
                    "close": snapshot.close,
                    "spread": snapshot.spread,
                    "volume": snapshot.trading_volume,
                    "source": snapshot.source,
                    "fetched_at_utc": snapshot.fetched_at.isoformat(timespec="seconds"),
                }
                for snapshot in cached_snapshots
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("尚無市場資料快取。")
    if cached_valuations:
        st.caption("最新估值快取")
        st.dataframe(
            [
                {
                    "ticker": valuation.ticker,
                    "trade_date": valuation.trade_date.isoformat(),
                    "pe_ratio": valuation.pe_ratio,
                    "pb_ratio": valuation.pb_ratio,
                    "dividend_yield": valuation.dividend_yield,
                    "source": valuation.source,
                    "fetched_at_utc": valuation.fetched_at.isoformat(timespec="seconds"),
                }
                for valuation in cached_valuations
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("尚無估值資料快取。")
    st.caption(f"目前財報三表科目快取：{cached_financial_count} 筆")
    if cached_filings:
        st.caption("公司文件快取")
        st.dataframe(
            [
                {
                    "股票": filing.ticker,
                    "類型": filing.document_type,
                    "標題": filing.title,
                    "來源": filing.source.publisher,
                    "日期": filing.source.published_at.isoformat()
                    if filing.source.published_at
                    else None,
                }
                for filing in cached_filings
            ],
            width="stretch",
            hide_index=True,
        )

with tabs[2]:
    render_section_header("補充資料", "手動補充新聞、法說或研究摘要，讓報告可以引用具體來源。")
    input_tabs = st.tabs(["新聞/研究摘要", "公司公開文件"])
    with input_tabs[0]:
        title = st.text_input("標題")
        publisher = st.text_input("來源", value="manual")
        published_at = st.date_input("日期", value=today_taipei())
        url = st.text_input("URL")
        text = st.text_area("內文", height=260)
        if st.button("匯入 RAG"):
            document = NewsFetcher.from_manual_text(
                title=title,
                text=text,
                publisher=publisher,
                published_at=published_at,
                url=url or None,
            )
            VectorStore().upsert_documents([document])
            matches = EntityMapper().match_document(document)
            with session_scope() as session:
                NewsRepository(session).upsert_document(
                    document,
                    [match.model_dump(mode="json") for match in matches],
                )
            st.success(f"已匯入：{document.id}")

    with input_tabs[1]:
        filing_ticker = st.selectbox("股票代號", options=allowed_tickers, index=allowed_tickers.index("2330") if "2330" in allowed_tickers else 0)
        filing_company = st.text_input("公司名稱", value=next((company.name for company in whitelist.companies() if company.ticker == filing_ticker), ""))
        filing_type = st.selectbox(
            "文件類型",
            options=["annual_report", "investor_presentation", "prospectus", "material_information", "company_disclosure"],
            format_func=lambda value: {
                "annual_report": "年報",
                "investor_presentation": "法說/投資人簡報",
                "prospectus": "公開說明書",
                "material_information": "重大訊息",
                "company_disclosure": "其他公司揭露",
            }.get(value, value),
        )
        filing_title = st.text_input("文件標題", key="filing_title")
        filing_publisher = st.text_input("文件來源", value="公司 IR / MOPS", key="filing_publisher")
        filing_date = st.date_input("文件日期", value=today_taipei(), key="filing_date")
        filing_url = st.text_input("文件 URL", key="filing_url")
        filing_text = st.text_area("文件文字", height=260, key="filing_text")
        filing_import_cols = st.columns(2)
        import_text_filing = filing_import_cols[0].button("匯入公司文件")
        import_url_filing = filing_import_cols[1].button("從 URL 抓取並匯入")
        if import_text_filing:
            if not filing_title or not filing_text:
                st.warning("請輸入文件標題與文字。")
            else:
                document = CompanyFilingFetcher.from_manual_text(
                    ticker=filing_ticker,
                    company_name=filing_company,
                    document_type=filing_type,
                    title=filing_title,
                    text=filing_text,
                    publisher=filing_publisher,
                    published_at=filing_date,
                    url=filing_url or None,
                )
                news_document = CompanyFilingRepository.to_news_document(document)
                VectorStore().upsert_documents([news_document])
                with session_scope() as session:
                    CompanyFilingRepository(session).upsert_document(document)
                tier = filing_source_tier(document)
                score = filing_quality_score(document, filing_ticker, filing_company)
                st.success(f"已匯入公司文件：{document.id}")
                st.caption(f"來源分級：{tier}；品質分數：{score}")
        if import_url_filing:
            if not filing_url:
                st.warning("請輸入文件 URL。")
            else:
                with st.spinner("正在抓取 URL 並匯入公司文件..."):
                    document = asyncio.run(
                        CompanyFilingFetcher().fetch_url_document(
                            url=filing_url,
                            ticker=filing_ticker,
                            company_name=filing_company,
                            document_type=filing_type,
                            publisher=filing_publisher,
                            published_at=filing_date,
                        )
                    )
                    news_document = CompanyFilingRepository.to_news_document(document)
                    VectorStore().upsert_documents([news_document])
                    with session_scope() as session:
                        CompanyFilingRepository(session).upsert_document(document)
                tier = filing_source_tier(document)
                score = filing_quality_score(document, filing_ticker, filing_company)
                st.success(f"已從 URL 匯入公司文件：{document.id}")
                st.caption(f"來源分級：{tier}；品質分數：{score}")

    with st.expander("進階：從 RSS 匯入"):
        render_section_header("RSS 匯入", "從既有資料源或指定 URL 抓取最新文本。")
        source_store = NewsSourceStore()
        configured_sources = source_store.load()
        if configured_sources:
            st.dataframe(
                [source.model_dump(mode="json") for source in configured_sources],
                width="stretch",
                hide_index=True,
            )
        feed_url = st.text_input("RSS URL")
        feed_publisher = st.text_input("來源名稱", value="rss")
        feed_limit = st.number_input("抓取筆數", min_value=1, max_value=50, value=10)
        if st.button("抓取 RSS"):
            if not feed_url:
                st.warning("請輸入 RSS URL。")
            else:
                with st.spinner("正在抓取 RSS..."):
                    result = asyncio.run(
                        IngestionPipeline().ingest_feeds(
                            url=feed_url,
                            publisher=feed_publisher,
                            limit=int(feed_limit),
                        )
                    )
                st.success(f"已匯入 {result['count']} 筆 RSS 內容。")
                if result["errors"]:
                    st.warning(result["errors"])

with tabs[3]:
    render_section_header("股票範圍", "這裡是系統可辨識的台股公司範圍；正式報告仍會再用資料證據篩選。")
    with st.expander("查看完整公司範圍"):
        st.json(SupplyChainWhitelist().raw)

with tabs[3]:
    render_section_header("自動排程", "設定固定時間自動產生分析。")
    schedule_store = ScheduleConfigStore()
    schedule_config = schedule_store.load()
    schedule_enabled = st.toggle("啟用每日排程", value=schedule_config.enabled)
    col_hour, col_minute = st.columns(2)
    with col_hour:
        schedule_hour = st.number_input("小時", min_value=0, max_value=23, value=schedule_config.hour)
    with col_minute:
        schedule_minute = st.number_input("分鐘", min_value=0, max_value=59, value=schedule_config.minute)
    schedule_topic = st.text_input("排程主題", value=schedule_config.topic)
    schedule_tickers = st.multiselect(
        "排程個股",
        options=sorted(SupplyChainWhitelist().allowed_tickers()),
        default=schedule_config.tickers,
    )
    schedule_lookback = st.number_input(
        "排程回看天數",
        min_value=1,
        max_value=180,
        value=schedule_config.lookback_days,
    )
    if st.button("儲存排程設定", type="primary"):
        if schedule_enabled and not schedule_tickers:
            st.warning("啟用每日排程時，請至少選擇一檔白名單股票。")
        else:
            saved = schedule_store.save(
                ScheduleConfig(
                    enabled=schedule_enabled,
                    hour=int(schedule_hour),
                    minute=int(schedule_minute),
                    topic=schedule_topic,
                    tickers=schedule_tickers,
                    lookback_days=int(schedule_lookback),
                    timezone="Asia/Taipei",
                )
            )
            st.success(f"已儲存：每日 {saved.timezone} {saved.hour:02d}:{saved.minute:02d}")
    with st.expander("進階：背景服務啟動指令"):
        st.info("只有需要啟動自動排程服務時才需要使用。")
        st.code(
            ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app worker -B --loglevel=INFO --pool=solo",
            language="bash",
        )

with tabs[3]:
    render_section_header("維護", "一般使用不需要查看；只有資料異常或服務連線問題時使用。")
    status = db_status()
    service_snapshot = service_status()
    service_metrics = maintenance_service_metrics(status, service_snapshot)
    service_cols = st.columns(len(service_metrics))
    for column, (label, value) in zip(service_cols, service_metrics.items()):
        column.metric(label, value)
    with st.expander("進階：服務細節"):
        st.json(status["settings"])
        st.json(status["integrity"])
        st.json(service_snapshot)
        st.dataframe(
            [
                {"table": table, **details}
                for table, details in status["tables"].items()
            ],
            width="stretch",
            hide_index=True,
        )
    with st.expander("進階：資料清理"):
        st.warning("清理操作會刪除歷史紀錄；不確定時請不要使用。")
        if st.button("清除失敗紀錄"):
            with session_scope() as session:
                deleted = AnalysisRunRepository(session).delete_failed()
            st.success(f"已清除 {deleted} 筆失敗紀錄。")
        stale_minutes = st.number_input("執行逾時分鐘", min_value=5, max_value=1440, value=60)
        if st.button("標記逾時任務"):
            stale_before = datetime.utcnow() - timedelta(minutes=int(stale_minutes))
            with session_scope() as session:
                marked = AnalysisRunRepository(session).mark_stale_running_failed(
                    stale_before,
                    "marked failed from Streamlit maintenance",
                )
            st.success(f"已標記 {marked} 筆逾時任務。")
        if st.button("修復失效報告連結"):
            with session_scope() as session:
                cleared = AnalysisRunRepository(session).clear_orphan_report_refs()
            st.success(f"已修復 {cleared} 筆報告連結。")
        cleanup_days = st.number_input("保留天數", min_value=1, max_value=3650, value=90)
        cleanup_before = datetime.combine(today_taipei() - timedelta(days=int(cleanup_days)), time.min)
        col_runs, col_reports = st.columns(2)
        with col_runs:
            if st.button("清除舊分析紀錄"):
                with session_scope() as session:
                    deleted = AnalysisRunRepository(session).delete_before(cleanup_before)
                st.success(f"已清除 {deleted} 筆 {cleanup_before.date().isoformat()} 前的分析紀錄。")
        with col_reports:
            if st.button("清除舊報告"):
                with session_scope() as session:
                    deleted = ReportRepository(session).delete_before(cleanup_before)
                st.success(f"已清除 {deleted} 筆 {cleanup_before.date().isoformat()} 前的報告。")
