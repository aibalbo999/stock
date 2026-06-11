from __future__ import annotations

from pathlib import Path

from app.ui.maintenance_incident_view import (
    incident_action_controls_intro_html,
    incident_card_html,
    incident_empty_card_html,
    incident_inbox_header_html,
    incident_list_html,
    incident_priority_summary_html,
)


def test_maintenance_incident_view_is_streamlit_free() -> None:
    source = Path("app/ui/maintenance_incident_view.py").read_text()

    assert "import streamlit" not in source
    assert "st." not in source


def test_incident_view_renders_header_and_escapes_badges() -> None:
    html = incident_inbox_header_html(["Critical <1>", "Warning & 2"])

    assert 'class="incident-inbox"' in html
    assert "待處理事件" in html
    assert "Critical &lt;1&gt;" in html
    assert "Warning &amp; 2" in html


def test_incident_view_renders_priority_summary_and_controls() -> None:
    summary_html = incident_priority_summary_html(
        {
            "state": "attention",
            "title": "先確認 <Warning>",
            "counts_label": "Critical 0 / Warning 1 / Info 0",
            "primary_action": "先確認事件",
            "secondary_action": "1 個跳轉入口。",
        }
    )
    controls_html = incident_action_controls_intro_html()

    assert 'class="incident-priority-summary is-attention"' in summary_html
    assert "先確認 &lt;Warning&gt;" in summary_html
    assert "事件處理操作" in controls_html
    assert "開啟對應頁面或任務檢視" in controls_html


def test_incident_view_renders_grouped_card_with_route_caption() -> None:
    html = incident_card_html(
        {
            "severity": 'critical" onclick="bad',
            "title": "<script>alert(1)</script>",
            "impact": "需要 <b>確認</b>",
            "next_action": "前往 > 維護",
            "repeat_count": 3,
        },
        route_text="開啟維護頁並檢視任務 refresh-0；另有 2 筆同類事件",
    )

    assert '<script>' not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "需要 &lt;b&gt;確認&lt;/b&gt;" in html
    assert "同類事件 3 筆" in html
    assert "開啟維護頁並檢視任務 refresh-0；另有 2 筆同類事件" in html


def test_incident_view_renders_list_shell_and_empty_card() -> None:
    empty_html = incident_empty_card_html()
    list_html = incident_list_html(empty_html)

    assert "目前沒有待處理事件" in empty_html
    assert 'class="incident-inbox is-list"' in list_html
    assert "incident-list" in list_html
