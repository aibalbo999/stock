from __future__ import annotations

from typing import Any

import streamlit as st

from app.services.report_quality import parse_quality_gate_from_markdown
from app.ui.api_loaders import load_api_json_or_default
from app.ui.dashboard_core import render_section_header
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.report_health import latest_report_health_summary
from app.ui.report_lifecycle import latest_report_lifecycle
from app.ui.report_center_presenter import (
    empty_report_action_summary,
    latest_report_picker_state,
    report_reader_decision_summary,
    report_run_detail_error_message,
    report_run_history_ids,
    report_run_history_rows,
)
from app.ui.report_center_history import render_report_history_debug_panel
from app.ui.report_panels import (
    candidate_rows,
    render_company_data_audit,
    render_quality_gate,
    render_reader_report,
)
from app.ui.report_follow_up_controls import render_follow_up_controls, render_follow_up_flash
from app.ui.report_html import report_html
from app.ui.report_center_view import (
    empty_report_action_html,
    empty_report_result_html,
    latest_report_picker_html,
    report_health_strip_html,
    report_lifecycle_action_html,
    report_lifecycle_strip_html,
    report_reader_decision_html,
)

__all__ = [
    "empty_report_action_summary",
    "latest_report_picker_state",
    "render_report_center",
    "report_reader_decision_summary",
    "report_run_detail_error_message",
    "report_run_history_ids",
    "report_run_history_rows",
]


def render_report_center() -> None:
    render_section_header(
        "報告中心", "查看每個主題的最新版 HTML 報告；舊版內容只保留在執行紀錄中追蹤。"
    )
    render_follow_up_flash()
    reports = load_api_json_or_default(
        "/reports?limit=5",
        [],
        error_message="讀取報告清單失敗",
    )
    task_summary = (
        {}
        if reports
        else load_api_json_or_default(
            "/tasks/summary?days=7&limit=10",
            {},
            error_message="讀取報告中心任務狀態失敗",
            notify="warning",
        )
    )
    pending_report_id = st.session_state.pop("pending_selected_report_id", None)
    picker = latest_report_picker_state(
        reports,
        pending_report_id=pending_report_id,
        current_report_id=st.session_state.get("selected_report_id"),
        task_summary=task_summary,
    )
    report_options = picker["options"]

    if report_options:
        report_ids = [report["id"] for report in report_options]
        selected_id = picker["selected_id"]
        st.session_state["selected_report_id"] = selected_id
        _render_latest_report_picker_summary(picker)
        if picker["mode"] == "multi_topic_latest":
            selected_id = st.selectbox(
                picker["selector_label"],
                options=report_ids,
                key="selected_report_id",
                format_func=lambda report_id: next(
                    report["label"] for report in report_options if report["id"] == report_id
                ),
            )
    else:
        selected_id = None
        _render_latest_report_picker_summary(picker)
        st.info(str(picker.get("summary_detail") or "尚無最新版報告。"))

    report_markdown = None
    report_title = "report"
    history_result = None
    if selected_id:
        report_payload = load_api_json_or_default(
            f"/reports/{int(selected_id)}",
            {},
            error_message="讀取報告內容失敗",
        )
        if isinstance(report_payload, dict) and report_payload:
            report_markdown = report_payload.get("markdown")
            report_title = report_payload.get("title") or "report"
            history_result = {
                "report_id": selected_id,
                "title": report_payload.get("title"),
                "topic": report_payload.get("topic"),
                "generated_at": report_payload.get("generated_at"),
                "tickers": report_payload.get("tickers") or [],
                "request": report_payload.get("request") or {},
                "quality_gate": report_payload.get("quality_gate")
                or parse_quality_gate_from_markdown(report_markdown or ""),
                "auto_follow_up": report_payload.get("auto_follow_up"),
                "candidate_whitelist": report_payload.get("candidate_whitelist") or [],
                "candidate_audit": report_payload.get("candidate_audit") or {},
            }
        if report_markdown:
            history_result = history_result or {
                "report_id": selected_id,
                "title": report_title,
                "quality_gate": parse_quality_gate_from_markdown(report_markdown),
            }

    if selected_id and report_markdown:
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
                render_follow_up_controls(int(selected_id), report_markdown, scope="history_report")
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
            empty_report_result_html(picker),
            unsafe_allow_html=True,
        )
        _render_empty_report_action(picker)

    render_report_history_debug_panel(
        selected_id=selected_id,
        report_title=report_title,
    )


def _render_latest_report_picker_summary(picker: dict[str, Any]) -> None:
    st.markdown(
        latest_report_picker_html(picker),
        unsafe_allow_html=True,
    )


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


def _render_empty_report_action(picker: dict[str, Any]) -> None:
    summary = empty_report_action_summary(picker)
    if not summary:
        return
    st.markdown(
        empty_report_action_html(summary),
        unsafe_allow_html=True,
    )
    render_operator_route_button(
        {
            "action_label": summary["action_label"],
            "route_hint": summary["route_hint"],
        },
        key="report_empty_state_primary_action",
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
