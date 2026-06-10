from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_report_workflow_status(source_context: FrontendSourceContext) -> dict:
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    report_state_source = ui_sources["report_state.py"]
    report_panels_source = ui_sources["report_panels.py"]
    report_follow_up_controls_source = ui_sources["report_follow_up_controls.py"]
    report_observability_panel_source = ui_sources["report_observability_panel.py"]
    report_center_source = ui_sources["report_center.py"]
    report_health_source = ui_sources["report_health.py"]
    report_lifecycle_source = ui_sources["report_lifecycle.py"]
    operator_decisions_source = ui_sources["operator_decisions.py"]
    style_source = (
        source_context.style_path.read_text(encoding="utf-8")
        if source_context.style_path.exists()
        else ""
    )
    report_debug_expander_index = report_center_source.find(
        'with st.expander("疑難排解：執行紀錄")'
    )
    report_delete_button_index = report_center_source.find('st.button("刪除此報告"')
    return {
        "frontend_report_workflow_status_extracted": True,
        "frontend_report_workflow_status_path": (
            "app/services/status_frontend_report_workflow.py"
        ),
        "ui_report_observability_summary_enabled": "/reports/observability/summary?limit=20"
        in ui_source
        and "報告生成觀測" in ui_source
        and "trace_captured_count" in ui_source
        and "keyword_fallback_count" in ui_source,
        "ui_report_observability_bottlenecks_enabled": (
            "def report_observability_bottleneck_rows("
        )
        in report_observability_panel_source
        and 'summary.get("bottlenecks")' in report_observability_panel_source
        and "優先優化清單" in report_observability_panel_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source,
        "ui_report_observability_recommendations_enabled": (
            "def report_observability_recommendation_rows("
        )
        in report_observability_panel_source
        and 'summary.get("recommendations")' in report_observability_panel_source
        and "建議處理順序" in report_observability_panel_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source,
        "ui_report_observability_graphrag_metrics_enabled": (
            "graph_reasoning_path_count" in report_observability_panel_source
            and "graph_reasoning_coverage_ratio" in report_observability_panel_source
            and "GraphRAG paths" in report_observability_panel_source
            and "Graph 覆蓋率" in report_observability_panel_source
        ),
        "ui_report_lifecycle_data_gap_prefill_enabled": (
            "from app.ui.data_gap_actions import data_gap_action_items"
            in report_lifecycle_source
            and "def _primary_data_gap_action(" in report_lifecycle_source
            and 'gap_action.get("route_hint")' in report_lifecycle_source
            and "primary_action_detail" in report_lifecycle_source
            and 'lifecycle.get("primary_action_detail"' in ui_source
            and 'key="report_lifecycle_primary_action"' in ui_source
        ),
        "ui_report_health_identity_enabled": (
            "def latest_report_health_summary(" in report_health_source
            and '"report_meta_label": _report_meta_label(' in report_health_source
            and "def _format_generated_at(" in report_health_source
            and '"title": report_payload.get("title")' in ui_source
            and '"generated_at": report_payload.get("generated_at")' in ui_source
            and 'summary.get("report_meta_label"' in ui_source
            and ".report-health-card em" in style_source
        ),
        "ui_report_health_action_enabled": (
            "def _follow_up_health_state(" in report_health_source
            and '"follow_up_state": follow_up_state' in report_health_source
            and '"rerun_running"' in report_health_source
            and '"blocked"' in report_health_source
            and "data_gap_action_items(" in report_health_source
            and 'summary.get("action_label"' in ui_source
            and 'summary.get("follow_up_state"' in ui_source
            and "report-health-action" in ui_source
            and ".report-health-action" in style_source
        ),
        "ui_report_quality_unknown_guard_enabled": (
            "def _quality_gate_known(" in report_lifecycle_source
            and 'quality_state = "unknown"' in report_lifecycle_source
            and "尚無法判斷品質門檻" in report_lifecycle_source
            and "確認品質門檻" in report_lifecycle_source
            and "def _quality_gate_known(" in report_health_source
            and '"quality_unknown"' in report_health_source
            and "尚無法判斷" in report_health_source
            and 'quality_stage.get("state") == "unknown"' in operator_decisions_source
            and "先確認報告品質狀態" in operator_decisions_source
        ),
        "ui_report_latest_only_picker_enabled": (
            'load_api_json_or_default(\n        "/reports?limit=5"' in report_center_source
            and "def latest_report_picker_state(" in report_center_source
            and '"single_latest"' in report_center_source
            and '"multi_topic_latest"' in report_center_source
            and "目前最新版報告" in report_center_source
            and "選擇主題最新版報告" in report_center_source
            and "建立分析後，這裡會顯示目前保留的最新版報告。" in report_center_source
            and ".latest-report-picker" in style_source
        ),
        "ui_report_empty_running_task_state_enabled": (
            '"/tasks/summary?days=7&limit=10"' in report_center_source
            and "task_summary=task_summary" in report_center_source
            and "def _latest_task_running(" in report_center_source
            and "def _task_running(" in report_center_source
            and "最新版報告生成中" in report_center_source
            and "最新任務正在背景執行；完成前不需要重複建立分析。"
            in report_center_source
            and '"action_label": "查看任務"' in report_center_source
            and '"route_hint": _task_route_hint(latest_running_task)' in report_center_source
            and 'key="report_empty_state_primary_action"' in report_center_source
            and (
                report_center_source.find('"/tasks/summary?days=7&limit=10"')
                < report_center_source.find("latest_report_picker_state(")
            )
        ),
        "ui_report_advanced_controls_progressive_disclosure_enabled": (
            'with st.expander("疑難排解：執行紀錄")' in report_center_source
            and 'with st.expander("報告管理")' not in report_center_source
            and "進階操作，只在需要移除最新版報告時使用。" in report_center_source
            and 'st.button("刪除此報告"' in report_center_source
            and report_debug_expander_index >= 0
            and report_delete_button_index >= 0
            and report_debug_expander_index < report_delete_button_index
            and 'with st.expander("原始紀錄內容"):' in report_center_source
            and 'with st.expander("背景任務狀態", expanded=False):' in report_center_source
        ),
        "ui_report_observability_panel_extracted": (
            ui_dir / "report_observability_panel.py"
        ).exists()
        and "def report_observability_metric_values(" in report_observability_panel_source
        and "def report_observability_bottleneck_rows(" in report_observability_panel_source
        and "def report_observability_recommendation_rows("
        in report_observability_panel_source
        and "graph_reasoning_path_count" in report_observability_panel_source
        and "def render_report_observability_panel(" in report_observability_panel_source
        and "from app.ui.report_observability_panel import render_report_observability_panel"
        in ui_source
        and "render_report_observability_panel(report_observability_summary)" in ui_source
        and "report_obs_cols" not in ui_source,
        "ui_report_observability_panel_path": "app/ui/report_observability_panel.py",
        "ui_report_state_extracted": (ui_dir / "report_state.py").exists()
        and "def hydrate_active_report_result(" in report_state_source
        and "def parse_json_object(" in report_state_source
        and "def hydrate_active_report_result(" not in dashboard_core_source
        and "def parse_json_object(" not in dashboard_core_source
        and "from app.ui.report_state import " in ui_source,
        "ui_report_state_path": "app/ui/report_state.py",
        "ui_report_panels_extracted": (ui_dir / "report_panels.py").exists()
        and "def render_quality_gate(" in report_panels_source
        and "def render_source_audit(" in report_panels_source
        and "def render_company_data_audit(" in report_panels_source
        and "def render_follow_up_controls(" not in report_panels_source
        and "def render_quality_gate(" not in dashboard_core_source
        and "from app.ui.report_panels import (" in ui_source,
        "ui_report_panels_path": "app/ui/report_panels.py",
        "ui_report_follow_up_controls_extracted": (
            ui_dir / "report_follow_up_controls.py"
        ).exists()
        and "def render_follow_up_controls(" in report_follow_up_controls_source
        and "def render_follow_up_flash(" in report_follow_up_controls_source
        and "def render_follow_up_controls(" not in report_panels_source
        and "def render_follow_up_flash(" not in report_panels_source
        and "def render_follow_up_controls(" not in dashboard_core_source
        and "from app.ui.report_follow_up_controls import" in ui_source,
        "ui_report_follow_up_controls_path": "app/ui/report_follow_up_controls.py",
    }
