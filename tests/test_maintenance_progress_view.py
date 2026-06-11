from __future__ import annotations

import importlib
from pathlib import Path


def _view_module():
    return importlib.import_module("app.ui.maintenance_progress_view")


def test_maintenance_progress_view_is_streamlit_free() -> None:
    _view_module()
    source = Path("app/ui/maintenance_progress_view.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_operator_summary_html_renders_actions_and_escapes_fields() -> None:
    view = _view_module()

    html = view.optimization_progress_operator_summary_html(
        {
            "state": 'ready" onclick="bad',
            "title": "核心 <完成>",
            "detail": "先驗證 & 再採購",
            "local_action": "套用 <defaults>",
            "paid_external": "TEJ & API 可暫緩",
            "free_validation": "免費檢查 <2>",
            "next_step": "重跑稽核 > 檢查",
            "command": ".venv/bin/python scripts/audit.py --flag '<x>'",
        }
    )

    assert 'class="optimization-progress-operator-summary is-ready&quot; onclick=&quot;bad"' in html
    assert "核心 &lt;完成&gt;" in html
    assert "先驗證 &amp; 再採購" in html
    assert "套用 &lt;defaults&gt;" in html
    assert "TEJ &amp; API 可暫緩" in html
    assert "免費檢查 &lt;2&gt;" in html
    assert "重跑稽核 &gt; 檢查" in html
    assert ".venv/bin/python scripts/audit.py --flag &#x27;&lt;x&gt;&#x27;" in html


def test_operator_summary_html_omits_blank_command() -> None:
    view = _view_module()

    html = view.optimization_progress_operator_summary_html(
        {
            "state": "ready",
            "title": "已完成",
            "detail": "沒有待處理缺口。",
            "local_action": "",
            "paid_external": "",
            "next_step": "維持觀測。",
            "command": "-",
        }
    )

    assert 'class="optimization-progress-operator-summary is-ready"' in html
    assert "<code>" not in html
    assert "<li>維持觀測。</li>" in html


def test_scope_summary_html_renders_scope_and_escapes_fields() -> None:
    view = _view_module()

    html = view.optimization_progress_scope_summary_html(
        {
            "state": "info",
            "title": "分母 <不同>",
            "detail": "優化追蹤 32 項 & 稽核 33 項。",
            "objective": "優化目標 32/32",
            "audit": "升級稽核 32/33",
            "excluded": "部署 preflight：Python <3.11>",
            "note": "這不是缺口漏算 & 屬部署前檢查。",
        }
    )

    assert 'class="optimization-progress-scope-summary is-info"' in html
    assert "分母 &lt;不同&gt;" in html
    assert "優化追蹤 32 項 &amp; 稽核 33 項。" in html
    assert "部署 preflight：Python &lt;3.11&gt;" in html
    assert "這不是缺口漏算 &amp; 屬部署前檢查。" in html
