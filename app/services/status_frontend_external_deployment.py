from __future__ import annotations

from app.services.status_frontend_external_deployment_domains import (
    frontend_external_deployment_domain_status,
)
from app.services.status_frontend_external_deployment_readiness import (
    frontend_external_deployment_readiness_status,
)
from app.services.status_frontend_sources import FrontendSourceContext


def frontend_external_deployment_status(source_context: FrontendSourceContext) -> dict:
    return {
        "frontend_external_deployment_status_extracted": True,
        "frontend_external_deployment_status_path": (
            "app/services/status_frontend_external_deployment.py"
        ),
        **frontend_external_deployment_domain_status(source_context),
        **frontend_external_deployment_readiness_status(source_context),
    }
