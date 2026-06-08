from __future__ import annotations

from app.services.status_frontend_task_failures import frontend_task_failure_status
from app.services.status_frontend_task_queue import frontend_task_queue_status
from app.services.status_frontend_sources import FrontendSourceContext


def frontend_task_ui_status(source_context: FrontendSourceContext) -> dict:
    return {
        "frontend_task_ui_status_extracted": True,
        "frontend_task_ui_status_path": "app/services/status_frontend_tasks.py",
        **frontend_task_queue_status(source_context),
        **frontend_task_failure_status(source_context),
    }
