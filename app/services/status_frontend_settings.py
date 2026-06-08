from __future__ import annotations

from app.services.status_frontend_maintenance import frontend_maintenance_ui_status
from app.services.status_frontend_settings_core import frontend_settings_core_status
from app.services.status_frontend_sources import FrontendSourceContext


def frontend_settings_ui_status(source_context: FrontendSourceContext) -> dict:
    return {
        "frontend_settings_ui_status_extracted": True,
        "frontend_settings_ui_status_path": "app/services/status_frontend_settings.py",
        **frontend_settings_core_status(source_context),
        **frontend_maintenance_ui_status(source_context),
    }
