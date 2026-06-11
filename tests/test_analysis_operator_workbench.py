from pathlib import Path


def test_analysis_operator_workbench_is_extracted_from_workspace() -> None:
    workspace_source = Path("app/ui/analysis_workspace.py").read_text()
    workbench_source = Path("app/ui/analysis_operator_workbench.py").read_text()

    assert (
        "from app.ui.analysis_operator_workbench import render_analysis_operator_workbench"
        in workspace_source
    )
    assert "render_analysis_operator_workbench()" in workspace_source
    assert "def render_analysis_operator_workbench(" in workbench_source
    assert 'load_api_json_or_default(\n        "/services/status"' in workbench_source
    assert 'load_api_json_or_default(\n        "/tasks/summary?days=7&limit=10"' in (
        workbench_source
    )
    assert 'load_api_json_or_default(\n        "/llm/quota"' in workbench_source
    assert 'load_api_json_or_default(\n        "/reports?limit=5"' in workbench_source
    assert "operator_next_best_action(" in workbench_source
    assert "operator_secondary_actions(" in workbench_source
    assert "operator_status_overall(" in workbench_source
    assert "operator_status_cards(" in workbench_source
    assert "operator_decision_html(primary_action, [], include_secondary=False)" in (
        workbench_source
    )
    assert "operator_secondary_actions_html(secondary_actions)" in workbench_source
    assert "operator_workbench_header_html(overall)" in workbench_source
    assert "operator_status_grid_html(card_html)" in workbench_source
    assert 'key="operator_route_primary_action"' in workbench_source
    assert 'key=f"operator_route_action_{index}"' in workbench_source

    assert "def _render_operator_workbench(" not in workspace_source
    assert 'load_api_json_or_default(\n        "/services/status"' not in workspace_source
    assert "operator_next_best_action(" not in workspace_source
    assert "operator_status_cards(" not in workspace_source
