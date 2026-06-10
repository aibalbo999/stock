from __future__ import annotations

from html import escape
from pathlib import Path
import streamlit as st

from app.services.runtime_identity import runtime_identity_status


STYLE_PATH = Path(__file__).with_name("styles") / "stock_dashboard.css"


def load_dashboard_css() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def configure_page(page_title: str = "台股 AI 產業鏈分析") -> None:
    st.set_page_config(page_title=page_title, layout="wide")
    load_dashboard_css()
    render_frontend_runtime_identity()


def render_frontend_runtime_identity() -> None:
    st.markdown(frontend_runtime_identity_html(runtime_identity_status()), unsafe_allow_html=True)


def frontend_runtime_identity_html(identity: dict) -> str:
    commit = str(identity.get("git_commit") or "")
    commit_short = str(identity.get("git_commit_short") or commit[:12])
    dirty = _runtime_bool_label(identity.get("git_dirty"))
    source = str(identity.get("source") or "unknown")
    return (
        '<div data-stock-frontend-runtime="true" '
        f'data-git-commit="{escape(commit, quote=True)}" '
        f'data-git-commit-short="{escape(commit_short, quote=True)}" '
        f'data-git-dirty="{dirty}" '
        f'data-source="{escape(source, quote=True)}" '
        'hidden aria-hidden="true"></div>'
    )


def _runtime_bool_label(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


def render_section_header(title: str, note: str = "") -> None:
    note_html = f'<div class="section-note">{escape(note)}</div>' if note else ""
    st.markdown(
        f"""
        <div class="section-head">
            <div>
                <div class="section-title">{escape(title)}</div>
                {note_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
