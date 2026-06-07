from __future__ import annotations

import streamlit as st

from app.ui.analysis_workspace import render_analysis_workspace
from app.ui.dashboard_core import configure_page
from app.ui.data_enrichment import render_data_enrichment
from app.ui.report_center import render_report_center
from app.ui.system_settings import render_system_settings

__all__ = [
    "configure_page",
    "render_analysis_workspace",
    "render_data_enrichment",
    "render_legacy_tabbed_app",
    "render_report_center",
    "render_system_settings",
]


def render_legacy_tabbed_app() -> None:
    tabs = st.tabs(["1 建立分析", "2 報告中心", "3 資料與補充", "4 設定與維護"])
    with tabs[0]:
        render_analysis_workspace()
    with tabs[1]:
        render_report_center()
    with tabs[2]:
        render_data_enrichment()
    with tabs[3]:
        render_system_settings()
