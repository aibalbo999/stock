from __future__ import annotations

import streamlit as st

from app.core.time import today_taipei
from app.ui.analysis_form_panel import render_analysis_form_panel
from app.ui.analysis_operator_workbench import render_analysis_operator_workbench
from app.ui.analysis_operator_presenter import (
    looks_like_operator_route as _looks_like_operator_route,
    operator_card_html as _operator_card_html,
    operator_decision_html as _operator_decision_html,
    operator_secondary_actions_html as _operator_secondary_actions_html,
    operator_source_label as _operator_source_label,
    operator_source_text as _operator_source_text,
    secondary_action_html as _secondary_action_html,
)
from app.ui.analysis_workspace_presenter import (
    analysis_submission_quota_pressure,
    analysis_submission_ready,
    analysis_submission_summary,
)
from app.ui.analysis_result_panel import render_analysis_result_panel
from app.ui.analysis_task_lookup_panel import render_analysis_task_lookup_panel
from app.ui.analysis_workspace_view import (
    workspace_flow_html,
    workspace_topbar_html,
)
from app.ui.dashboard_core import render_section_header


__all__ = [
    "analysis_submission_quota_pressure",
    "analysis_submission_ready",
    "analysis_submission_summary",
    "_looks_like_operator_route",
    "_operator_card_html",
    "_operator_decision_html",
    "_operator_secondary_actions_html",
    "_operator_source_label",
    "_operator_source_text",
    "_secondary_action_html",
    "render_analysis_workspace",
]


def render_analysis_workspace() -> None:
    st.markdown(
        workspace_topbar_html(today_taipei().isoformat()),
        unsafe_allow_html=True,
    )
    render_analysis_operator_workbench()
    st.markdown(workspace_flow_html(), unsafe_allow_html=True)
    render_section_header(
        "建立一次分析", "預設使用 AI 拆解主題並抓取國內外資料；不確定時維持預設即可。"
    )
    analysis_config_col, analysis_result_col = st.columns([0.36, 0.64], gap="large")
    with analysis_config_col:
        investor_capital = render_analysis_form_panel()
        render_analysis_task_lookup_panel()

    with analysis_result_col:
        render_analysis_result_panel(investor_capital=investor_capital)
