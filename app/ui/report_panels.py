from __future__ import annotations

from importlib import import_module
from typing import Optional

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.report_html import (
    report_html,
)
from app.ui.report_formatters import confidence_label, metric_int, metric_percent


def render_reader_report(markdown: str, result: Optional[dict] = None) -> None:
    render_report_document(report_html(markdown, result), height=820)


def load_legacy_streamlit_components():
    return import_module("streamlit.components.v1")


def render_report_document(
    document_html: str,
    *,
    height: int = 820,
    streamlit_module=st,
    components_importer=load_legacy_streamlit_components,
) -> None:
    iframe = getattr(streamlit_module, "iframe", None)
    if callable(iframe):
        iframe(document_html, width="stretch", height=height)
        return
    components_importer().html(document_html, height=height, scrolling=True)


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
                    source.get("title", "") for source in candidate.get("evidence_sources", [])[:2]
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
    audit = load_api_json_or_default(
        f"/reports/{report_id}/company-data-audit",
        {},
        error_message="個股資料足夠性檢查失敗",
        notify="warning",
    )
    if not isinstance(audit, dict) or not audit:
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
