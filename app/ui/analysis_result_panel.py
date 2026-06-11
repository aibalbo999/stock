from __future__ import annotations

import streamlit as st

from app.ui.analysis_workspace_view import empty_analysis_result_html
from app.ui.dashboard_core import render_section_header
from app.ui.report_follow_up_controls import render_follow_up_controls
from app.ui.report_formatters import metric_count_from_payload
from app.ui.report_html import report_html
from app.ui.report_panels import (
    candidate_rows,
    render_company_data_audit,
    render_market_errors,
    render_quality_gate,
    render_reader_report,
    render_source_audit,
)
from app.ui.report_state import hydrate_active_report_result


def render_analysis_result_panel(*, investor_capital: int) -> None:
    result = st.session_state.get("last_analysis_result")
    if not result:
        st.markdown(empty_analysis_result_html(), unsafe_allow_html=True)
        return

    result = hydrate_active_report_result(result)
    report_markdown = result["report"]["markdown"]
    analysis_metrics = (result.get("quality_gate") or {}).get("metrics") or {}
    metric_cols = st.columns(4)
    metric_cols[0].metric("報告", f"#{result['report_id']}")
    metric_cols[1].metric(
        "正式分析股票",
        metric_count_from_payload(
            result, "promoted_tickers", analysis_metrics, "promoted_count", 0
        ),
    )
    metric_cols[2].metric("候選清單", len(result.get("candidate_whitelist", [])))
    metric_cols[3].metric("設定總資金", f"{int(investor_capital):,}")
    render_market_errors(result)

    render_section_header("本次分析結果", "先看重點報告；資料細節只在需要查核時展開。")
    result_tabs = st.tabs(["重點報告", "資料查核"])
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
        render_follow_up_controls(
            int(result["report_id"]), report_markdown, scope="analysis_result"
        )
        with st.expander("資料來源概況"):
            render_source_audit(result)
        if result.get("candidate_whitelist"):
            st.markdown("**候選清單驗證**")
            st.dataframe(
                candidate_rows(result["candidate_whitelist"]),
                width="stretch",
                hide_index=True,
            )
        with st.expander("進階：原始報告文字"):
            st.markdown(report_markdown)
