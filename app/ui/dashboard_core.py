from __future__ import annotations

from html import escape
from pathlib import Path
import streamlit as st


STYLE_PATH = Path(__file__).with_name("styles") / "stock_dashboard.css"


def load_dashboard_css() -> None:
    css = STYLE_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def configure_page(page_title: str = "台股 AI 產業鏈分析") -> None:
    st.set_page_config(page_title=page_title, layout="wide")
    load_dashboard_css()


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
