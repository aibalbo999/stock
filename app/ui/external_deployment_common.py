from __future__ import annotations

EXTERNAL_SMOKE_COMMAND_KEYS = frozenset(
    {
        "smoke_cli",
        "smoke_command",
        "smoke_commands",
        "sample_contract_cli",
        "payload_dry_run_cli",
        "import_smoke_cli",
        "neo4j_graphrag_smoke_command",
        "company_filing_render_smoke_command",
        "structured_company_filing_smoke_command",
    }
)
EXTERNAL_DETAIL_KEYS = frozenset(
    {
        "fallback_reason",
        "connection_error",
        "runtime_error",
        "error",
        "reason",
    }
)


def external_deployment_warning_rows(upgrade_audit: dict) -> list[dict]:
    return [
        {
            "面向": _external_area_label(item),
            "能力": item.get("label") or item.get("capability") or "-",
            "狀態": item.get("status") or "-",
            "警示層級": _external_warning_level(item),
            "說明": _external_warning_detail(item),
            "診斷指令": "\n".join(external_smoke_commands_from_payload(item)) or "-",
            "處理方向": item.get("remediation") or "-",
        }
        for item in external_deployment_warning_items(upgrade_audit)
    ]


def external_deployment_smoke_commands(upgrade_audit: dict) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for item in external_deployment_warning_items(upgrade_audit):
        for command in external_smoke_commands_from_payload(item):
            if command in seen:
                continue
            seen.add(command)
            commands.append(command)
    return commands


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


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def ready_label(value: object) -> str:
    return "Ready" if value else "待配置"


def yes_no(value: object) -> str:
    return "是" if value else "否"


def _external_area_label(item: dict) -> str:
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    return area_labels.get(str(item.get("area") or ""), item.get("area") or "-")


def _external_warning_level(item: dict) -> str:
    if item.get("severity") == "fail":
        return "需處理"
    if item.get("optional") or item.get("_warning_source") == "optional_warnings":
        return "外部選配"
    return "注意"


def _external_warning_detail(item: dict) -> str:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    parts = [str(item.get("detail") or "").strip()]
    nested_detail = _first_external_detail_value(evidence)
    if nested_detail:
        parts.append(nested_detail)
    unique_parts: list[str] = []
    for part in parts:
        if not part or part in unique_parts:
            continue
        unique_parts.append(part)
    return "；".join(unique_parts) if unique_parts else "-"


def _first_external_detail_value(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in EXTERNAL_DETAIL_KEYS and str(value or "").strip():
                return str(value).strip()
        for value in payload.values():
            detail = _first_external_detail_value(value)
            if detail:
                return detail
    if isinstance(payload, list):
        for value in payload:
            detail = _first_external_detail_value(value)
            if detail:
                return detail
    return None
