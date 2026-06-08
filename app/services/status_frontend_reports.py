from __future__ import annotations

from app.services.status_frontend_report_rendering import (
    frontend_report_rendering_status,
)
from app.services.status_frontend_report_workflow import frontend_report_workflow_status
from app.services.status_frontend_sources import FrontendSourceContext


def frontend_report_ui_status(source_context: FrontendSourceContext) -> dict:
    return {
        "frontend_report_ui_status_extracted": True,
        "frontend_report_ui_status_path": "app/services/status_frontend_reports.py",
        **frontend_report_rendering_status(source_context),
        **frontend_report_workflow_status(source_context),
    }
