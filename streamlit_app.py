import asyncio
import json
from datetime import datetime, time, timedelta
from html import escape
from typing import Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

from app.core.config import get_settings
from app.core.time import today_taipei
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
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=180)
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
        if len(cells) < 2 or cells[0] in {"股票", "項目"}:
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


def metric_percent(value: object) -> str:
    return "未評估" if value is None else f"{float(value or 0):.0%}"


def metric_int(value: object) -> str:
    return "未評估" if value is None else str(value)


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
    amount = action_policy.get("max_deployable_amount")
    amount_label = f"{int(amount):,} 元" if amount is not None else "-"
    report_id = result.get("report_id") if result else "-"
    promoted = len(result.get("promoted_tickers", [])) if result else metrics.get("promoted_count", "-")
    candidate_count = len(result.get("candidate_whitelist", [])) if result else "-"
    source_count = metrics.get("dynamic_source_count", 0)
    publisher_count = metric_int(metrics.get("source_unique_publishers"))
    timestamp_coverage = metric_percent(metrics.get("source_timestamp_coverage"))
    recent_coverage = metric_percent(metrics.get("source_recent_coverage"))

    summary_items = markdown_items(markdown, "一頁摘要", limit=3)
    action_items = markdown_items(markdown, "下一步行動", limit=3)
    guard_items = markdown_items(markdown, "投資行動限制", limit=3)
    investment_rows = markdown_table_rows(markdown, "投資建議", limit=6)
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
            detail_html(markdown, "個別公司分析", "個別公司分析"),
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
  .trust-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:10px; }}
  .metric {{ background:#FFFFFF; border:1px solid #D7DEE8; border-radius:8px; padding:14px; }}
  .metric span {{ display:block; color:#667085; font-size:13px; }}
  .metric strong {{ display:block; margin-top:4px; font-size:20px; }}
  .status {{ display:inline-block; border-radius:999px; padding:6px 10px; font-size:13px; font-weight:700; }}
  .ready {{ background:#E4F8F0; color:#087443; }}
  .caution {{ background:#FFF4DA; color:#8A5A12; }}
  .insufficient {{ background:#FDEAE7; color:#B42318; }}
  .unknown {{ background:#E8EEF6; color:#344054; }}
  .panel {{ background:#FFFFFF; border:1px solid #D7DEE8; border-radius:8px; padding:16px; margin-top:12px; }}
  ul {{ margin:8px 0 0; padding-left:20px; }}
  li {{ margin:7px 0; line-height:1.55; }}
  .stock-list {{ display:grid; gap:10px; }}
  .stock-card {{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; border:1px solid #D7DEE8; border-radius:8px; padding:14px; background:#FFFFFF; }}
  .ticker {{ font-weight:800; margin-bottom:6px; }}
  .reason {{ color:#53657D; font-size:14px; line-height:1.5; }}
  .decision {{ white-space:nowrap; background:#E7F0FF; color:#1D4ED8; border-radius:999px; padding:6px 10px; font-weight:700; font-size:13px; }}
  details {{ background:#F9FBFD; border:1px solid #D7DEE8; border-radius:8px; padding:12px 14px; margin:8px 0; }}
  summary {{ cursor:pointer; font-weight:700; }}
  @media (max-width:760px) {{ .grid,.trust-grid {{ grid-template-columns:1fr 1fr; }} .stock-card {{ display:block; }} .decision {{ display:inline-block; margin-top:10px; }} }}
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
    </div>
  </section>
  <section class="panel"><h2>重點摘要</h2><ul>{summary_html}</ul></section>
  {"<section class='panel'><h2>投資行動限制</h2><ul>" + guard_html + "</ul></section>" if guard_html else ""}
  <section class="panel"><h2>下一步</h2><ul>{action_html}</ul></section>
  <section class="panel"><h2>個股建議</h2><div class="stock-list">{investment_html}</div></section>
  {"<section class='panel'><h2>二次篩選</h2><ul>" + final_html + "</ul></section>" if final_html else ""}
  <section class="panel"><h2>展開看細節</h2>{details or "<p class='muted'>目前沒有更多細節。</p>"}</section>
</main>
</body>
</html>
"""


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
                "主要來源": "；".join(candidate.get("evidence_titles", [])[:2]),
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

    query_sample = audit.get("dynamic_query_sample") or []
    if query_sample:
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
    cols[2].metric("候選覆蓋", f"{float(metrics.get('candidate_supported_ratio') or 0):.0%}")
    amount = action_policy.get("max_deployable_amount")
    cols[3].metric("可投入上限", f"{int(amount):,}" if amount is not None else "-")
    source_cols = st.columns(4)
    source_cols[0].metric("來源篇數", metrics.get("dynamic_source_count", 0))
    source_cols[1].metric("來源家數", metric_int(metrics.get("source_unique_publishers")))
    source_cols[2].metric("日期可查", metric_percent(metrics.get("source_timestamp_coverage")))
    source_cols[3].metric("近期資料", metric_percent(metrics.get("source_recent_coverage")))
    if action_policy.get("label"):
        st.caption(f"投資行動狀態：{action_policy['label']}")

    issues = []
    for item in gate.get("blockers", []) or []:
        issues.append({"等級": "阻擋", "項目": item})
    for item in gate.get("warnings", []) or []:
        issues.append({"等級": "警示", "項目": item})
    if issues:
        st.dataframe(issues, width="stretch", hide_index=True)


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
            selected_id = st.selectbox(
                "選擇報告",
                options=[report["id"] for report in report_options],
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
            with session_scope() as session:
                report = ReportRepository(session).get(int(selected_id))
                report_markdown = report.markdown if report else None
                report_title = report.title if report else "report"
            if report_markdown:
                history_result = {
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
    count_cols = st.columns(4)
    count_cols[0].metric("股價快取", table_counts.get("stock_price_snapshots", {}).get("count") or 0)
    count_cols[1].metric("月營收快取", table_counts.get("monthly_revenue_snapshots", {}).get("count") or 0)
    count_cols[2].metric("財報三表快取", table_counts.get("financial_metric_snapshots", {}).get("count") or 0)
    count_cols[3].metric("估值快取", table_counts.get("valuation_metric_snapshots", {}).get("count") or 0)

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

    refresh_cols = st.columns(3)
    refresh_price = refresh_cols[0].button("刷新股價", type="primary")
    refresh_financials = refresh_cols[1].button("刷新 5 年財報")
    refresh_valuations = refresh_cols[2].button("刷新估值")

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

    with session_scope() as session:
        cached_snapshots = MarketRepository(session).latest_by_tickers(allowed_tickers)
        cached_valuations = ValuationMetricRepository(session).latest_by_tickers(allowed_tickers)
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

with tabs[2]:
    render_section_header("補充資料", "手動補充新聞、法說或研究摘要，讓報告可以引用具體來源。")
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
    service_cols = st.columns(4)
    service_cols[0].metric("資料庫", "正常" if status.get("integrity", {}).get("ok", True) else "異常")
    service_cols[1].metric("Redis", "正常" if service_snapshot.get("redis", {}).get("ok") else "未連線")
    service_cols[2].metric("AI Key", service_snapshot.get("gemini", {}).get("key_count", 0))
    service_cols[3].metric("市場資料", "可用" if service_snapshot.get("finmind", {}).get("mode") else "檢查")
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
