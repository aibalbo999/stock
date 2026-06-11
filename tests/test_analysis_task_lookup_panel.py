from __future__ import annotations

import importlib
from pathlib import Path


def _lookup_module():
    return importlib.import_module("app.ui.analysis_task_lookup_panel")


def test_analysis_task_lookup_panel_owns_task_status_controls() -> None:
    module = _lookup_module()
    source = Path("app/ui/analysis_task_lookup_panel.py").read_text()

    assert callable(module.render_analysis_task_lookup_panel)
    assert 'with st.expander("疑難排解：查詢背景分析")' in source
    assert 'last_task_id = st.session_state.get("last_async_task_id")' in source
    assert "render_task_status_panel(" in source
    assert 'refresh_key="refresh_analysis_task_status"' in source
    assert 'apply_result_key="apply_analysis_task_result"' in source
    assert 'task_state_key="last_async_task_id"' in source


def test_analysis_workspace_delegates_task_lookup_panel() -> None:
    _lookup_module()
    source = Path("app/ui/analysis_workspace.py").read_text()

    assert (
        "from app.ui.analysis_task_lookup_panel import render_analysis_task_lookup_panel"
        in source
    )
    assert "render_analysis_task_lookup_panel()" in source
    assert 'with st.expander("疑難排解：查詢背景分析")' not in source
    assert (
        'load_api_json_or_default(\n                        f"/tasks/{task_id}/run"'
        not in source
    )
