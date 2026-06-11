from __future__ import annotations

from app.ui.analysis_workspace_view import (
    analysis_form_intro_html,
    analysis_submission_summary_html,
    empty_analysis_result_html,
    operator_action_controls_html,
    operator_status_grid_html,
    operator_workbench_header_html,
    workspace_flow_html,
    workspace_topbar_html,
)


def test_analysis_workspace_view_renders_operator_shell_sections() -> None:
    topbar_html = workspace_topbar_html("2026-06-12")
    flow_html = workspace_flow_html()
    empty_html = empty_analysis_result_html()
    controls_html = operator_action_controls_html(primary=False)

    assert "workspace-topbar is-compact" in topbar_html
    assert "Asia/Taipei 2026-06-12" in topbar_html
    assert "workflow-strip is-compact" in flow_html
    assert "workspace-ledger is-compact" in flow_html
    assert "result-shell" in empty_html
    assert "等待分析結果" in empty_html
    assert "operator-action-controls" in controls_html
    assert "次要操作" in controls_html


def test_analysis_workspace_view_renders_form_intro_note() -> None:
    html = analysis_form_intro_html("輸入 <主題> & 建立候選股票。")

    assert 'class="compact-note"' in html
    assert "輸入 &lt;主題&gt; &amp; 建立候選股票。" in html


def test_analysis_workspace_view_escapes_submission_and_status_values() -> None:
    submission_html = analysis_submission_summary_html(
        {
            "state": 'ready" onclick="bad',
            "title": "<b>可送出</b>",
            "detail": "AI > 電子",
            "quota_pressure_class": "high",
            "quota_pressure": "額度 < 高",
            "quota_advice": "先確認",
            "next_step": "按下送出",
        }
    )
    header_html = operator_workbench_header_html(
        {
            "state": 'attention" onclick="bad',
            "label": "<script>alert(1)</script>",
            "detail": "先看 > 建議",
        }
    )
    grid_html = operator_status_grid_html("<article>card</article>")

    assert "<b>" not in submission_html
    assert "&lt;b&gt;可送出&lt;/b&gt;" in submission_html
    assert "AI &gt; 電子" in submission_html
    assert "額度 &lt; 高｜先確認" in submission_html
    assert "<script>" not in header_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in header_html
    assert "先看 &gt; 建議" in header_html
    assert "operator-status-grid" in grid_html
