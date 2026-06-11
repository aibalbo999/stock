from __future__ import annotations

import importlib
from pathlib import Path


def _history_module():
    return importlib.import_module("app.ui.report_center_history")


def test_report_center_history_panel_module_owns_debug_expander() -> None:
    module = _history_module()
    source = Path("app/ui/report_center_history.py").read_text()

    assert callable(module.render_report_history_debug_panel)
    assert 'with st.expander("疑難排解：執行紀錄")' in source
    assert "render_section_header(" in source
    assert "report_run_history_rows(runs)" in source
    assert "report_run_history_ids(runs)" in source
    assert "render_task_status_panel(" in source


def test_report_center_history_panel_owns_destructive_action_guards() -> None:
    _history_module()
    source = Path("app/ui/report_center_history.py").read_text()
    report_center_source = Path("app/ui/report_center.py").read_text()

    assert "report_delete_confirmed = st.checkbox(" in source
    assert 'key=f"confirm_delete_report_{selected_id}"' in source
    assert 'disabled=not report_delete_confirmed' in source
    assert "run_delete_confirmed = st.checkbox(" in source
    assert 'key=f"confirm_delete_run_{selected_run_id}"' in source
    assert 'key=f"delete_run_{selected_run_id}"' in source
    assert "刪除報告會移除目前最新版報告與安全範圍內的報告檔" in source
    assert "刪除分析紀錄只會移除此筆執行歷史，不會刪除目前最新版報告" in source
    assert 'with st.expander("疑難排解：執行紀錄")' not in report_center_source
    assert "render_report_history_debug_panel(" in report_center_source
