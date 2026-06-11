from __future__ import annotations

from pathlib import Path

from app.ui.system_settings_scope_view import scope_source_summary_html


def test_system_settings_scope_view_is_streamlit_free() -> None:
    source = Path("app/ui/system_settings_scope_view.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_scope_source_summary_html_explains_static_scope_and_escapes() -> None:
    html = scope_source_summary_html(
        {
            "state": "ready",
            "title": "系統靜態股票範圍",
            "detail": "目前可辨識 2 檔股票、1 個產業分類、3 個風險詞組。",
            "source": "來源：data/<scope>.json",
            "next_step": "本頁不是本次報告的動態候選名單。",
            "fallback_hint": "若任務被白名單或輸入擋下，請先回分析工作區調整股票。",
        }
    )

    assert 'class="scope-source-summary is-ready"' in html
    assert "白名單來源摘要" in html
    assert "系統靜態股票範圍" in html
    assert "data/&lt;scope&gt;.json" in html
    assert "不是本次報告的動態候選名單" in html
    assert "若任務被白名單或輸入擋下" in html
