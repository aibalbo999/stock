from __future__ import annotations

from app.services.external_deployment_readiness import (
    EXTERNAL_DETAIL_KEYS as EXTERNAL_DETAIL_KEYS,
    EXTERNAL_ENABLEMENT_METADATA as EXTERNAL_ENABLEMENT_METADATA,
    EXTERNAL_LOCAL_ACTION_METADATA as EXTERNAL_LOCAL_ACTION_METADATA,
    EXTERNAL_READINESS_METADATA as EXTERNAL_READINESS_METADATA,
    EXTERNAL_SMOKE_COMMAND_KEYS as EXTERNAL_SMOKE_COMMAND_KEYS,
    append_external_command as _append_external_command,
    collect_external_smoke_commands as _collect_external_smoke_commands,
    external_deployment_command_summary as _external_deployment_command_summary,
    external_deployment_enablement_profile as _external_deployment_enablement_profile,
    external_deployment_item_by_capability as _external_deployment_item_by_capability,
    external_deployment_item_ready as _external_deployment_item_ready,
    external_deployment_local_action as _external_deployment_local_action,
    external_deployment_readiness_decision as _external_deployment_readiness_decision,
    external_deployment_readiness_items as _external_deployment_readiness_items,
    external_deployment_readiness_metadata as _external_deployment_readiness_metadata,
    external_deployment_readiness_rows as _external_deployment_readiness_rows,
    external_deployment_readiness_state as _external_deployment_readiness_state,
    external_deployment_smoke_commands as _external_deployment_smoke_commands,
    external_deployment_warning_items as _external_deployment_warning_items,
    external_deployment_warning_rows as _external_deployment_warning_rows,
    external_smoke_commands_from_payload as _external_smoke_commands_from_payload,
    local_dependency_last_start_rows as _local_dependency_last_start_rows,
    local_dependency_repair_rows as _local_dependency_repair_rows,
    local_dependency_status_rows as _local_dependency_status_rows,
    ready_label as _ready_label,
    string_list as _string_list,
    yes_no as _yes_no,
)


def external_deployment_readiness_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    return _external_deployment_readiness_rows(upgrade_audit, local_dependency_status)


def external_deployment_readiness_items(upgrade_audit: dict) -> list[dict]:
    return _external_deployment_readiness_items(upgrade_audit)


def external_deployment_readiness_metadata(item: dict) -> dict:
    return _external_deployment_readiness_metadata(item)


def external_deployment_enablement_profile(item: dict) -> dict:
    return _external_deployment_enablement_profile(item)


def external_deployment_local_action(
    item: dict,
    upgrade_audit: dict,
    *,
    local_dependency_status: dict | None = None,
) -> dict:
    return _external_deployment_local_action(
        item,
        upgrade_audit,
        local_dependency_status=local_dependency_status,
    )


def local_dependency_status_rows(service_snapshot: dict) -> list[dict]:
    return _local_dependency_status_rows(service_snapshot)


def local_dependency_repair_rows(service_snapshot: dict) -> list[dict]:
    return _local_dependency_repair_rows(service_snapshot)


def local_dependency_last_start_rows(service_snapshot: dict) -> list[dict]:
    return _local_dependency_last_start_rows(service_snapshot)


def external_deployment_readiness_state(item: dict) -> str:
    return _external_deployment_readiness_state(item)


def external_deployment_readiness_decision(item: dict) -> str:
    return _external_deployment_readiness_decision(item)


def external_deployment_command_summary(commands: list[str]) -> str:
    return _external_deployment_command_summary(commands)


def external_deployment_warning_rows(upgrade_audit: dict) -> list[dict]:
    return _external_deployment_warning_rows(upgrade_audit)


def external_deployment_smoke_commands(upgrade_audit: dict) -> list[str]:
    return _external_deployment_smoke_commands(upgrade_audit)


def external_deployment_warning_items(upgrade_audit: dict) -> list[dict]:
    return _external_deployment_warning_items(upgrade_audit)


def external_deployment_item_by_capability(upgrade_audit: dict, capability: str) -> dict:
    return _external_deployment_item_by_capability(upgrade_audit, capability)


def external_deployment_item_ready(item: dict) -> bool:
    return _external_deployment_item_ready(item)


def external_smoke_commands_from_payload(payload: object) -> list[str]:
    return _external_smoke_commands_from_payload(payload)


def collect_external_smoke_commands(payload: object, commands: list[str]) -> None:
    _collect_external_smoke_commands(payload, commands)


def append_external_command(value: object, commands: list[str]) -> None:
    _append_external_command(value, commands)


def string_list(value: object) -> list[str]:
    return _string_list(value)


def ready_label(value: object) -> str:
    return _ready_label(value)


def yes_no(value: object) -> str:
    return _yes_no(value)
