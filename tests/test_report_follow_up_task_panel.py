from __future__ import annotations

import importlib
from pathlib import Path


def _task_panel_module():
    return importlib.import_module("app.ui.report_follow_up_task_panel")


def test_follow_up_task_panel_owns_background_task_status_flow() -> None:
    module = _task_panel_module()
    source = Path("app/ui/report_follow_up_task_panel.py").read_text()

    assert callable(module.render_follow_up_task_status_panel)
    assert 'last_follow_up_task_id = streamlit_module.session_state.get("last_follow_up_task_id")' in source
    assert 'with streamlit_module.expander("背景補強任務狀態", expanded=True):' in source
    assert 'key=f"followup_task_lookup_{key_suffix}"' in source
    assert 'refresh_key=f"refresh_followup_task_{key_suffix}"' in source
    assert 'task_state_key="last_follow_up_task_id"' in source
    assert '"套用背景補強結果"' in source
    assert 'streamlit_module.session_state["follow_up_flash"]' in source
    assert "follow_up_result_message(result, summary_text)" in source


def test_follow_up_controls_delegate_task_status_panel() -> None:
    _task_panel_module()
    source = Path("app/ui/report_follow_up_controls.py").read_text()

    assert (
        "from app.ui.report_follow_up_task_panel import render_follow_up_task_status_panel"
        in source
    )
    assert "render_follow_up_task_status_panel(key_suffix, streamlit_module=st)" in source
    assert 'with st.expander("背景補強任務狀態", expanded=True):' not in source
    assert '"套用背景補強結果"' not in source
