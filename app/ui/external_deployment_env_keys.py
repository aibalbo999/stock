from __future__ import annotations

from app.services.external_deployment_env_gaps import (
    external_deployment_env_key_rows as _external_deployment_env_key_rows,
)


def external_deployment_env_key_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    return _external_deployment_env_key_rows(upgrade_audit, service_snapshot)
