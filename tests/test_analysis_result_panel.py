from pathlib import Path


def test_analysis_result_panel_is_extracted_from_workspace() -> None:
    workspace_source = Path("app/ui/analysis_workspace.py").read_text()
    panel_source = Path("app/ui/analysis_result_panel.py").read_text()

    assert "from app.ui.analysis_result_panel import render_analysis_result_panel" in (
        workspace_source
    )
    assert "render_analysis_result_panel(investor_capital=investor_capital)" in (
        workspace_source
    )
    assert "def render_analysis_result_panel(" in panel_source
    assert "last_analysis_result" in panel_source
    assert "hydrate_active_report_result(result)" in panel_source
    assert "render_market_errors(result)" in panel_source
    assert 'render_section_header("本次分析結果"' in panel_source
    assert 'st.tabs(["重點報告", "資料查核"])' in panel_source
    assert "st.download_button(" in panel_source
    assert "render_reader_report(report_markdown, result)" in panel_source
    assert "render_quality_gate(result)" in panel_source
    assert "render_company_data_audit(int(result[\"report_id\"]))" in panel_source
    assert 'scope="analysis_result"' in panel_source
    assert "render_source_audit(result)" in panel_source
    assert "candidate_rows(result[\"candidate_whitelist\"])" in panel_source
    assert "empty_analysis_result_html()" in panel_source

    assert "last_analysis_result" not in workspace_source
    assert "render_reader_report(report_markdown, result)" not in workspace_source
    assert 'scope="analysis_result"' not in workspace_source
