from __future__ import annotations

from app.ui.external_deployment_common import (
    external_deployment_readiness_rows as _external_deployment_readiness_rows,
    external_deployment_smoke_commands as _external_deployment_smoke_commands,
    external_deployment_warning_rows as _external_deployment_warning_rows,
    local_dependency_last_start_rows as _local_dependency_last_start_rows,
    local_dependency_repair_rows as _local_dependency_repair_rows,
    local_dependency_status_rows as _local_dependency_status_rows,
)
from app.ui.external_deployment_env_keys import (
    external_deployment_env_check_detail_rows as _external_deployment_env_check_detail_rows,
    external_deployment_env_check_summary_rows as _external_deployment_env_check_summary_rows,
    external_deployment_env_key_rows as _external_deployment_env_key_rows,
    external_deployment_env_resolution_rows as _external_deployment_env_resolution_rows,
)
from app.ui.external_deployment_neo4j import (
    local_neo4j_operation_rows as _local_neo4j_operation_rows,
)
from app.ui.external_deployment_structured_api import (
    structured_filing_api_operation_rows as _structured_filing_api_operation_rows,
)
from app.ui.external_deployment_unlocker import (
    high_risk_filing_unlocker_rows as _high_risk_filing_unlocker_rows,
    local_unlocker_operation_rows as _local_unlocker_operation_rows,
)


def external_deployment_warning_rows(upgrade_audit: dict) -> list[dict]:
    return _external_deployment_warning_rows(upgrade_audit)


def external_deployment_readiness_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    return _external_deployment_readiness_rows(upgrade_audit, local_dependency_status)


def external_deployment_env_key_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    return _external_deployment_env_key_rows(upgrade_audit, service_snapshot)


def external_deployment_env_resolution_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    return _external_deployment_env_resolution_rows(upgrade_audit, service_snapshot)


def external_deployment_env_check_summary_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
    *,
    env_file: str = ".env",
) -> list[dict]:
    return _external_deployment_env_check_summary_rows(
        upgrade_audit,
        service_snapshot,
        env_file=env_file,
    )


def external_deployment_env_check_detail_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
    *,
    target: str = "host",
    env_file: str = ".env",
) -> list[dict]:
    return _external_deployment_env_check_detail_rows(
        upgrade_audit,
        service_snapshot,
        target=target,
        env_file=env_file,
    )


def local_dependency_status_rows(service_snapshot: dict) -> list[dict]:
    return _local_dependency_status_rows(service_snapshot)


def local_dependency_last_start_rows(service_snapshot: dict) -> list[dict]:
    return _local_dependency_last_start_rows(service_snapshot)


def local_dependency_repair_rows(service_snapshot: dict) -> list[dict]:
    return _local_dependency_repair_rows(service_snapshot)


def external_deployment_smoke_commands(upgrade_audit: dict) -> list[str]:
    return _external_deployment_smoke_commands(upgrade_audit)


def high_risk_filing_unlocker_rows(upgrade_audit: dict) -> list[dict]:
    return _high_risk_filing_unlocker_rows(upgrade_audit)


def local_unlocker_operation_rows(upgrade_audit: dict) -> list[dict]:
    return _local_unlocker_operation_rows(upgrade_audit)


def local_neo4j_operation_rows(upgrade_audit: dict) -> list[dict]:
    return _local_neo4j_operation_rows(upgrade_audit)


def structured_filing_api_operation_rows(upgrade_audit: dict) -> list[dict]:
    return _structured_filing_api_operation_rows(upgrade_audit)
