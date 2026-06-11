from __future__ import annotations

from app.ui.maintenance_incident_presenter import (
    incident_action_controls_intro_html,
    incident_action_priority_summary,
    incident_inbox_header_html,
    incident_list_html,
    incident_priority_summary_html,
)


def test_maintenance_incident_presenter_renders_grouped_operator_inbox() -> None:
    incidents = [
        {
            "severity": "warning",
            "category": "data_source",
            "title": "資料來源抓取失敗",
            "impact": "最新版報告可能缺少最新市場或公司資料。",
            "next_action": "到維護頁重試此任務",
            "action_label": "重試任務",
            "route_hint": f"task:refresh-{index}",
            "retryable": True,
        }
        for index in range(3)
    ]

    header_html = incident_inbox_header_html(incidents)
    summary_html = incident_priority_summary_html(
        incident_action_priority_summary(incidents)
    )
    list_html = incident_list_html(incidents)
    controls_html = incident_action_controls_intro_html()
    combined = "\n".join([header_html, summary_html, list_html, controls_html])

    assert "待處理事件" in header_html
    assert "Warning 3" in header_html
    assert "incident-priority-summary is-attention" in summary_html
    assert "先確認 3 個 Warning 事件" in summary_html
    assert "3 個可重試任務可直接在下方操作" in summary_html
    assert combined.count("資料來源抓取失敗") == 1
    assert "同類事件 3 筆" in list_html
    assert "另有 2 筆同類事件" in list_html
    assert "開啟維護頁並檢視任務 refresh-0" in list_html
    assert "task:refresh-" not in combined
    assert "處理事件" in controls_html


def test_maintenance_incident_presenter_escapes_operator_values() -> None:
    html = incident_list_html(
        [
            {
                "severity": 'critical" onclick="bad',
                "title": "<script>alert(1)</script>",
                "impact": "需要 <b>確認</b>",
                "next_action": "前往 > 維護",
                "route_hint": "data_enrichment:company_filings_fetch:2330,2317",
            }
        ]
    )

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "需要 &lt;b&gt;確認&lt;/b&gt;" in html
    assert "開啟資料補強，準備補抓公司文件：2330、2317" in html
