from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_report_ui_status(source_context: FrontendSourceContext) -> dict:
    root = source_context.root
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    report_state_source = ui_sources["report_state.py"]
    report_panels_source = ui_sources["report_panels.py"]
    report_follow_up_controls_source = ui_sources["report_follow_up_controls.py"]
    report_markdown_source = ui_sources["report_markdown.py"]
    report_candidate_audit_source = ui_sources["report_candidate_audit.py"]
    report_formatters_source = ui_sources["report_formatters.py"]
    report_sections_source = ui_sources["report_sections.py"]
    report_html_source = ui_sources["report_html.py"]
    report_observability_panel_source = ui_sources["report_observability_panel.py"]
    report_style_path = source_context.report_style_path
    return {
        "frontend_report_ui_status_extracted": True,
        "frontend_report_ui_status_path": "app/services/status_frontend_reports.py",
        "report_html_renderer_path": "app/ui/report_html.py",
        "report_html_renderer_lines": len(report_html_source.splitlines())
        if report_html_source
        else None,
        "report_html_renderer_extracted": (ui_dir / "report_html.py").exists()
        and "def report_html(" in report_html_source
        and "def report_html(" not in dashboard_core_source
        and "from app.ui.report_html import (" in ui_source,
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
        "ui_report_observability_panel_extracted": (
            ui_dir / "report_observability_panel.py"
        ).exists()
        and "def report_observability_metric_values(" in report_observability_panel_source
        and "def report_observability_bottleneck_rows(" in report_observability_panel_source
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
        "ui_report_markdown_helpers_extracted": (ui_dir / "report_markdown.py").exists()
        and "def markdown_table_rows(" in report_markdown_source
        and "def markdown_table_rows_by_header(" in report_markdown_source
        and "def first_tranche_allocation_label(" in report_markdown_source
        and "def markdown_table_rows(" not in report_html_source
        and "def first_tranche_allocation_label(" not in report_html_source
        and "from app.ui.report_markdown import (" in ui_source,
        "ui_report_markdown_helpers_path": "app/ui/report_markdown.py",
        "ui_report_candidate_audit_extracted": (
            ui_dir / "report_candidate_audit.py"
        ).exists()
        and "def candidate_audit_html(" in report_candidate_audit_source
        and "def candidate_source_matches_display_entity(" in report_candidate_audit_source
        and "def candidate_audit_html(" not in report_html_source
        and "def candidate_source_matches_display_entity(" not in report_html_source
        and "from app.ui.report_candidate_audit import" in ui_source,
        "ui_report_candidate_audit_path": "app/ui/report_candidate_audit.py",
        "ui_report_formatters_extracted": (ui_dir / "report_formatters.py").exists()
        and "def metric_count_from_payload(" in report_formatters_source
        and "def quality_issue_html(" in report_formatters_source
        and "def auto_follow_up_status_html(" in report_formatters_source
        and "def metric_count_from_payload(" not in report_html_source
        and "def quality_issue_html(" not in report_html_source
        and "def auto_follow_up_status_html(" not in report_html_source
        and "from app.ui.report_formatters import" in ui_source,
        "ui_report_formatters_path": "app/ui/report_formatters.py",
        "ui_report_sections_extracted": (ui_dir / "report_sections.py").exists()
        and "def comparison_matrix_html(" in report_sections_source
        and "def credibility_html(" in report_sections_source
        and "def follow_up_tasks_html(" in report_sections_source
        and "def comparison_matrix_html(" not in report_html_source
        and "def credibility_html(" not in report_html_source
        and "def follow_up_tasks_html(" not in report_html_source
        and "from app.ui.report_sections import (" in ui_source,
        "ui_report_sections_path": "app/ui/report_sections.py",
        "external_report_css_path": str(report_style_path.relative_to(root)),
        "external_report_css_loaded": report_style_path.exists()
        and "REPORT_HTML_STYLE_PATH.read_text" in ui_source
        and "<style>{report_css}</style>" in ui_source
        and "<style>\n  :root" not in ui_source,
    }
