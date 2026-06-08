from __future__ import annotations

from app.services.status_frontend_data_enrichment_runtime import (
    frontend_data_enrichment_runtime_status,
)
from app.services.status_frontend_data_enrichment_tabs import (
    frontend_data_enrichment_tabs_status,
)
from app.services.status_frontend_sources import FrontendSourceContext


def frontend_data_enrichment_status(source_context: FrontendSourceContext) -> dict:
    return {
        "frontend_data_enrichment_status_extracted": True,
        "frontend_data_enrichment_status_path": (
            "app/services/status_frontend_data_enrichment.py"
        ),
        **frontend_data_enrichment_tabs_status(source_context),
        **frontend_data_enrichment_runtime_status(source_context),
    }
