from pathlib import Path


def test_report_center_document_panel_is_extracted_from_report_center() -> None:
    report_center_source = Path("app/ui/report_center.py").read_text()
    document_source = Path("app/ui/report_center_document.py").read_text()

    assert "from app.ui.report_center_document import render_report_center_document" in (
        report_center_source
    )
    assert "render_report_center_document(" in report_center_source
    assert "def render_report_center_document(" in document_source
    assert 'load_api_json_or_default(\n        f"/reports/{int(selected_id)}/follow-up/plan"' in (
        document_source
    )
    assert "latest_report_lifecycle(history_result or {}, follow_up_plan)" in document_source
    assert "latest_report_health_summary(history_result or {}, follow_up_plan)" in document_source
    assert "report_reader_decision_summary(lifecycle, health_summary)" in document_source
    assert "report_html(report_markdown, history_result)" in document_source
    assert "st.download_button(" in document_source
    assert 'st.tabs(["重點報告", "資料查核", "完整文字"])' in document_source
    assert "render_reader_report(report_markdown, history_result)" in document_source
    assert "render_quality_gate(history_result)" in document_source
    assert "render_company_data_audit(int(selected_id))" in document_source
    assert "render_follow_up_controls(" in document_source
    assert 'scope="history_report"' in document_source
    assert "candidate_rows(candidates)" in document_source

    assert 'load_api_json_or_default(\n            f"/reports/{int(selected_id)}/follow-up/plan"' not in (
        report_center_source
    )
    assert "history_tabs = st.tabs(" not in report_center_source
    assert 'scope="history_report"' not in report_center_source
