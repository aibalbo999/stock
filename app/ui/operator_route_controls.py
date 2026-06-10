from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.operator_routes import operator_route_target


def render_operator_route_button(
    action: dict[str, Any],
    *,
    key: str,
    primary: bool = False,
    show_caption: bool = True,
    use_container_width: bool = True,
) -> None:
    target = operator_route_target(action.get("route_hint"))
    label = str(
        action.get("action_label")
        or action.get("primary_action")
        or action.get("title")
        or target.get("caption")
        or "開啟"
    )
    if st.button(
        label,
        key=key,
        type="primary" if primary else "secondary",
        use_container_width=use_container_width,
        help=str(target.get("caption") or ""),
    ):
        for state_key, value in (target.get("session_updates") or {}).items():
            st.session_state[state_key] = value
        st.switch_page(str(target["page"]))
    if show_caption:
        st.caption(str(target.get("caption") or ""))
