from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


def frontend_report_rendering_status(source_context: FrontendSourceContext) -> dict:
    root = source_context.root
    ui_dir = source_context.ui_dir
    ui_source = source_context.ui_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    report_markdown_source = ui_sources["report_markdown.py"]
    report_candidate_audit_source = ui_sources["report_candidate_audit.py"]
    report_formatters_source = ui_sources["report_formatters.py"]
    report_sections_source = ui_sources["report_sections.py"]
    report_html_source = ui_sources["report_html.py"]
    report_style_path = source_context.report_style_path
    return {
        "frontend_report_rendering_status_extracted": True,
        "frontend_report_rendering_status_path": (
            "app/services/status_frontend_report_rendering.py"
        ),
        "report_html_renderer_path": "app/ui/report_html.py",
        "report_html_renderer_lines": len(report_html_source.splitlines())
        if report_html_source
        else None,
        "report_html_renderer_extracted": (ui_dir / "report_html.py").exists()
        and "def report_html(" in report_html_source
        and "def report_html(" not in dashboard_core_source
        and "from app.ui.report_html import (" in ui_source,
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
