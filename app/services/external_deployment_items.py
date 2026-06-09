from __future__ import annotations

from app.services.external_deployment_profiles import (
    EXTERNAL_READINESS_METADATA,
    EXTERNAL_SMOKE_COMMAND_KEYS,
)


def external_deployment_readiness_items(upgrade_audit: dict) -> list[dict]:
    if not isinstance(upgrade_audit, dict):
        return []
    items_with_index: list[tuple[int, dict]] = []
    seen: set[tuple[str, str]] = set()
    index = 0
    for source_key in ("checks", "failures", "warnings", "optional_warnings", "all_warnings"):
        source_items = upgrade_audit.get(source_key)
        if not isinstance(source_items, list):
            continue
        for raw_item in source_items:
            if not isinstance(raw_item, dict) or not _is_external_readiness_item(raw_item):
                continue
            key = (str(raw_item.get("area") or ""), str(raw_item.get("capability") or ""))
            if key in seen:
                continue
            seen.add(key)
            item = dict(raw_item)
            item["_warning_source"] = source_key
            items_with_index.append((index, item))
            index += 1
    return [
        item
        for _, item in sorted(
            items_with_index,
            key=lambda indexed_item: _external_readiness_sort_key(indexed_item[1], indexed_item[0]),
        )
    ]


def external_deployment_warning_items(upgrade_audit: dict) -> list[dict]:
    if not isinstance(upgrade_audit, dict):
        return []
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source_key in ("failures", "warnings", "optional_warnings", "all_warnings", "checks"):
        source_items = upgrade_audit.get(source_key)
        if not isinstance(source_items, list):
            continue
        for raw_item in source_items:
            if not isinstance(raw_item, dict):
                continue
            if not raw_item.get("external_integration"):
                continue
            if source_key == "checks" and raw_item.get("severity") == "pass":
                continue
            key = (str(raw_item.get("area") or ""), str(raw_item.get("capability") or ""))
            if key in seen:
                continue
            seen.add(key)
            item = dict(raw_item)
            item["_warning_source"] = source_key
            items.append(item)
    return items


def external_deployment_item_by_capability(upgrade_audit: dict, capability: str) -> dict:
    if not isinstance(upgrade_audit, dict):
        return {}
    for source_key in ("failures", "warnings", "optional_warnings", "all_warnings", "checks"):
        source_items = upgrade_audit.get(source_key)
        if not isinstance(source_items, list):
            continue
        for raw_item in source_items:
            if not isinstance(raw_item, dict):
                continue
            if raw_item.get("capability") != capability:
                continue
            if not raw_item.get("external_integration"):
                continue
            item = dict(raw_item)
            item["_warning_source"] = source_key
            return item
    return {}


def external_deployment_readiness_metadata(item: dict) -> dict:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    metadata = EXTERNAL_READINESS_METADATA.get(key, {})
    return {
        "priority": str(metadata.get("priority") or "P2"),
        "impact": str(metadata.get("impact") or item.get("detail") or "-"),
    }


def external_deployment_item_ready(item: dict) -> bool:
    return _external_readiness_item_ready(item)


def external_readiness_item_ready(item: dict) -> bool:
    return _external_readiness_item_ready(item)


def external_smoke_commands_from_payload(payload: object) -> list[str]:
    commands: list[str] = []
    collect_external_smoke_commands(payload, commands)
    deduped: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped


def collect_external_smoke_commands(payload: object, commands: list[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            if (
                key_text in EXTERNAL_SMOKE_COMMAND_KEYS
                or key_text.endswith("_smoke_cli")
                or key_text.endswith("_smoke_command")
            ):
                append_external_command(value, commands)
            else:
                collect_external_smoke_commands(value, commands)
    elif isinstance(payload, list):
        for value in payload:
            collect_external_smoke_commands(value, commands)


def append_external_command(value: object, commands: list[str]) -> None:
    if isinstance(value, str):
        command = value.strip()
        if command:
            commands.append(command)
        return
    if isinstance(value, list):
        for item in value:
            append_external_command(item, commands)
        return
    if isinstance(value, dict):
        collect_external_smoke_commands(value, commands)


def _is_external_readiness_item(item: dict) -> bool:
    if not item.get("external_integration"):
        return False
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    return bool(item.get("deployment_check") or key in EXTERNAL_READINESS_METADATA)


def _external_readiness_item_ready(item: dict) -> bool:
    if item.get("severity") == "pass" or item.get("status") == "ready":
        return True
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    if key == ("data_business_logic", "company_filing_high_risk_unlocker"):
        return bool(
            evidence.get("high_risk_mitigation_ready")
            or evidence.get("unlocker_provider_ready")
            or evidence.get("captcha_challenge_ready")
        )
    if key == ("data_business_logic", "company_filing_browser_or_proxy_fallback"):
        return bool(
            evidence.get("ready")
            or evidence.get("browser_or_proxy_fallback_configured")
            or evidence.get("browser_render_configured")
            or evidence.get("playwright_render_configured")
        )
    return bool(
        evidence.get("ready")
        or evidence.get("connection_ok")
        or evidence.get("neo4j_ready")
        or evidence.get("unlocker_provider_ready")
        or evidence.get("captcha_challenge_ready")
        or evidence.get("browser_or_proxy_fallback_configured")
        or evidence.get("playwright_render_configured")
    )


def _external_readiness_sort_key(item: dict, index: int) -> tuple[int, int, int]:
    severity_order = {"fail": 0, "warn": 1, "pass": 2}
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    metadata = external_deployment_readiness_metadata(item)
    return (
        severity_order.get(str(item.get("severity") or ""), 3),
        priority_order.get(metadata["priority"], 4),
        index,
    )


__all__ = [
    "append_external_command",
    "collect_external_smoke_commands",
    "external_deployment_item_by_capability",
    "external_deployment_item_ready",
    "external_deployment_readiness_items",
    "external_deployment_readiness_metadata",
    "external_deployment_warning_items",
    "external_readiness_item_ready",
    "external_smoke_commands_from_payload",
]
