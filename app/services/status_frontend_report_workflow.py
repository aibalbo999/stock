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
    report_lifecycle_source = ui_sources["report_lifecycle.py"]
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
