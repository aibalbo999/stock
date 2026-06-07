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

from app.ui.report_html import (
    confidence_label,
    markdown_table_rows,
    metric_int,
    metric_percent,
    report_html,
)

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
