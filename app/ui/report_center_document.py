from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.report_center_presenter import report_reader_decision_summary
from app.ui.report_center_view import (
    report_health_strip_html,
    report_lifecycle_action_html,
    report_lifecycle_strip_html,
    report_reader_decision_html,
)
from app.ui.report_follow_up_controls import render_follow_up_controls
from app.ui.report_health import latest_report_health_summary
from app.ui.report_html import report_html
from app.ui.report_lifecycle import latest_report_lifecycle
from app.ui.report_panels import (
    candidate_rows,
    render_company_data_audit,
    render_quality_gate,
    render_reader_report,
)


def render_report_center_document(
    *,
    selected_id: int,
    report_markdown: str,
    history_result: dict | None,
) -> None:
    follow_up_plan = load_api_json_or_default(
        f"/reports/{int(selected_id)}/follow-up/plan",
        {},
        error_message="讀取補強計畫失敗",
        notify="warning",
    )
    lifecycle = latest_report_lifecycle(history_result or {}, follow_up_plan)
    health_summary = latest_report_health_summary(history_result or {}, follow_up_plan)
    _render_report_lifecycle_strip(lifecycle)
    _render_report_reader_decision_summary(
        report_reader_decision_summary(lifecycle, health_summary)
    )
    _render_report_lifecycle_action(lifecycle)
    _render_report_health_strip(health_summary)
    history_html = report_html(report_markdown, history_result)
    report_download_cols = st.columns(2, gap="small")
    with report_download_cols[0]:
        st.download_button(
            "下載 HTML",
            data=history_html,
            file_name=f"report_{selected_id}.html",
            mime="text/html",
        )
    with report_download_cols[1]:
        st.download_button(
            "下載 Markdown",
            data=report_markdown,
            file_name=f"report_{selected_id}.md",
            mime="text/markdown",
        )

    history_tabs = st.tabs(["重點報告", "資料查核", "完整文字"])
    with history_tabs[0]:
        render_reader_report(report_markdown, history_result)
    with history_tabs[1]:
        if history_result:
            render_quality_gate(history_result)
            render_company_data_audit(int(selected_id))
            render_follow_up_controls(
                int(selected_id), report_markdown, scope="history_report"
            )
            candidates = history_result.get("candidate_whitelist") or []
            if candidates:
                with st.expander("候選公司審計"):
                    st.dataframe(candidate_rows(candidates), width="stretch", hide_index=True)
        else:
            st.info("此份報告尚無可解析的品質門檻。")
    with history_tabs[2]:
        st.markdown(report_markdown)


def _render_report_lifecycle_strip(lifecycle: dict) -> None:
    st.markdown(
        report_lifecycle_strip_html(lifecycle),
        unsafe_allow_html=True,
    )


def _render_report_lifecycle_action(lifecycle: dict) -> None:
    route_hint = lifecycle.get("route_hint")
    primary_action = lifecycle.get("primary_action")
    if not route_hint or not primary_action:
        return
    st.markdown(
        report_lifecycle_action_html(),
        unsafe_allow_html=True,
    )
    render_operator_route_button(
        {
            "action_label": primary_action,
            "route_hint": route_hint,
        },
        key="report_lifecycle_primary_action",
        primary=True,
        show_caption=True,
    )


def _render_report_reader_decision_summary(summary: dict[str, str]) -> None:
    if not summary:
        return
    st.markdown(
        report_reader_decision_html(summary),
        unsafe_allow_html=True,
    )


def _render_report_health_strip(summary: dict[str, str]) -> None:
    st.markdown(
        report_health_strip_html(summary),
        unsafe_allow_html=True,
    )
