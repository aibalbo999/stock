from __future__ import annotations

import streamlit as st

from app.ui.api_loaders import load_api_json_or_default
from app.ui.analysis_operator_presenter import (
    latest_report_id as _latest_report_id,
    operator_card_html,
    operator_decision_html,
    operator_secondary_actions_html,
)
from app.ui.analysis_workspace_view import (
    operator_action_controls_html,
    operator_status_grid_html,
    operator_workbench_header_html,
)
from app.ui.operator_decisions import (
    MAX_SECONDARY_ACTIONS,
    operator_next_best_action,
    operator_secondary_actions,
)
from app.ui.operator_route_controls import render_operator_route_button
from app.ui.operator_status import (
    operator_status_cards,
    operator_status_overall,
)


def render_analysis_operator_workbench() -> None:
    service_snapshot = load_api_json_or_default(
        "/services/status",
        {},
        error_message="讀取系統狀態失敗",
        notify="warning",
    )
    task_summary = load_api_json_or_default(
        "/tasks/summary?days=7&limit=10",
        {},
        error_message="讀取任務摘要失敗",
        notify="warning",
    )
    quota = load_api_json_or_default(
        "/llm/quota",
        {},
        error_message="讀取模型額度失敗",
        notify="warning",
    )
    reports = load_api_json_or_default(
        "/reports?limit=5",
        [],
        error_message="讀取最新版報告失敗",
        notify="warning",
    )
    if not isinstance(reports, list):
        reports = []
    latest_report_id = _latest_report_id(reports)
    latest_report_payload = {}
    latest_follow_up_plan = {}
    if latest_report_id is not None:
        latest_report_payload = load_api_json_or_default(
            f"/reports/{int(latest_report_id)}",
            {},
            error_message="讀取首頁報告狀態失敗",
            notify="warning",
        )
        latest_follow_up_plan = load_api_json_or_default(
            f"/reports/{int(latest_report_id)}/follow-up/plan",
            {},
            error_message="讀取首頁補強計畫失敗",
            notify="warning",
        )
    primary_action = operator_next_best_action(
        service_snapshot,
        task_summary,
        quota,
        reports,
        latest_report_payload,
        latest_follow_up_plan,
    )
    secondary_actions = operator_secondary_actions(
        service_snapshot,
        task_summary,
        quota,
        reports,
        latest_report_payload,
        latest_follow_up_plan,
        primary_action=primary_action,
    )
    overall = operator_status_overall(service_snapshot, task_summary, reports)
    cards = operator_status_cards(service_snapshot, task_summary, quota, reports)
    card_html = "\n".join(operator_card_html(card) for card in cards)
    st.markdown(
        operator_decision_html(primary_action, [], include_secondary=False),
        unsafe_allow_html=True,
    )
    _render_operator_primary_action_control(primary_action)
    if secondary_actions:
        st.markdown(operator_secondary_actions_html(secondary_actions), unsafe_allow_html=True)
    _render_operator_action_controls(secondary_actions)
    st.markdown(operator_workbench_header_html(overall), unsafe_allow_html=True)
    st.markdown(operator_status_grid_html(card_html), unsafe_allow_html=True)


def _render_operator_primary_action_control(primary_action: dict) -> None:
    st.markdown(operator_action_controls_html(primary=True), unsafe_allow_html=True)
    _render_operator_route_button(
        primary_action,
        key="operator_route_primary_action",
        primary=True,
        show_caption=False,
    )


def _render_operator_action_controls(secondary_actions: list[dict]) -> None:
    if not secondary_actions:
        return
    st.markdown(operator_action_controls_html(), unsafe_allow_html=True)
    actions = secondary_actions[:MAX_SECONDARY_ACTIONS]
    columns = st.columns(len(actions), gap="small")
    for index, action in enumerate(actions):
        with columns[index]:
            _render_operator_route_button(
                action,
                key=f"operator_route_action_{index}",
            )


def _render_operator_route_button(
    action: dict,
    *,
    key: str,
    primary: bool = False,
    show_caption: bool = True,
) -> None:
    render_operator_route_button(
        action,
        key=key,
        primary=primary,
        show_caption=show_caption,
    )
