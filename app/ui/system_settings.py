from __future__ import annotations

import streamlit as st

from app.services.whitelist import SupplyChainWhitelist
from app.ui.system_settings_maintenance import render_maintenance_tab
from app.ui.system_settings_schedule import render_schedule_tab
from app.ui.system_settings_scope import render_scope_tab


def render_system_settings() -> None:
    settings_whitelist = SupplyChainWhitelist()
    settings_tabs = st.tabs(["股票範圍", "自動排程", "維護"])

    with settings_tabs[0]:
        render_scope_tab(settings_whitelist)

    with settings_tabs[1]:
        render_schedule_tab(sorted(settings_whitelist.allowed_tickers()))

    with settings_tabs[2]:
        render_maintenance_tab()
