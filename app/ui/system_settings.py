from __future__ import annotations

import streamlit as st

from app.services.whitelist import SupplyChainWhitelist
from app.ui.system_settings_maintenance import render_maintenance_tab
from app.ui.system_settings_schedule import render_schedule_tab
from app.ui.system_settings_scope import render_scope_tab


SETTINGS_SECTION_LABELS = ("股票範圍", "自動排程", "維護")


def render_system_settings() -> None:
    settings_whitelist = SupplyChainWhitelist()
    pending_section = st.session_state.pop("pending_settings_section", None)
    maintenance_focus = maintenance_focus_from_pending_section(pending_section)
    if maintenance_focus:
        st.session_state["pending_maintenance_focus"] = maintenance_focus
    if pending_section is not None or st.session_state.get("settings_section") not in (
        SETTINGS_SECTION_LABELS
    ):
        st.session_state["settings_section"] = settings_section_label(pending_section)
    settings_section = st.radio(
        "系統設定區塊",
        SETTINGS_SECTION_LABELS,
        horizontal=True,
        key="settings_section",
        label_visibility="collapsed",
    )

    if settings_section == "股票範圍":
        render_scope_tab(settings_whitelist)
    elif settings_section == "自動排程":
        render_schedule_tab(sorted(settings_whitelist.allowed_tickers()))
    else:
        render_maintenance_tab()


def settings_section_label(pending_section: str | None) -> str:
    section = str(pending_section or "").strip()
    if section in {"maintenance", "ai_quota", "maintenance_local_defaults"}:
        return "維護"
    if section == "schedule":
        return "自動排程"
    return "股票範圍"


def maintenance_focus_from_pending_section(pending_section: str | None) -> str | None:
    section = str(pending_section or "").strip()
    if section == "ai_quota":
        return "ai_quota"
    if section == "maintenance_local_defaults":
        return "external_deployment"
    return None
