from pathlib import Path


def test_analysis_form_panel_is_extracted_from_workspace() -> None:
    workspace_source = Path("app/ui/analysis_workspace.py").read_text()
    panel_source = Path("app/ui/analysis_form_panel.py").read_text()

    assert "from app.ui.analysis_form_panel import render_analysis_form_panel" in (
        workspace_source
    )
    assert "investor_capital = render_analysis_form_panel()" in workspace_source
    assert "def render_analysis_form_panel(" in panel_source
    assert 'with st.form("analysis_form")' in panel_source
    assert "analysis_form_intro_html()" in panel_source
    assert "analysis_quota_confirmed = st.checkbox(" in panel_source
    assert 'key="confirm_analysis_submission_quota_usage"' in panel_source
    assert "我了解這會送出分析背景任務並消耗 AI/API 額度" in panel_source
    assert "避免誤觸與免費額度消耗" in panel_source
    assert "analysis_submission_summary(" in panel_source
    assert "def _render_analysis_submission_summary(" in panel_source
    assert "_render_analysis_submission_summary(submission_summary)" in panel_source
    assert "disabled=not analysis_submission_ready(" in panel_source
    assert 'submit_api_task(\n                "/pipeline/run_discovered_async"' in panel_source
    assert 'submit_api_task(\n                "/reports/generate_async"' in panel_source

    assert 'with st.form("analysis_form")' not in workspace_source
    assert "analysis_quota_confirmed = st.checkbox(" not in workspace_source
    assert 'submit_api_task(\n                "/pipeline/run_discovered_async"' not in (
        workspace_source
    )
    assert 'submit_api_task(\n                "/reports/generate_async"' not in workspace_source
