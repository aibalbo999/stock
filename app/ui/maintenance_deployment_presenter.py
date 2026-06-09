from __future__ import annotations


def external_deployment_effective_gap_rows(local_projection: dict) -> list[dict]:
    if not isinstance(local_projection, dict):
        return []
    if not any(
        key in local_projection
        for key in (
            "current_pending",
            "available_local_default_gap_count",
            "remaining_pending",
        )
    ):
        return []
    local_capabilities = _projection_capability_summary(
        local_projection.get("local_default_capabilities")
    )
    remaining_capabilities = _projection_capability_summary(
        local_projection.get("remaining_capabilities")
    )
    rows = [
        {
            "項目": "原始外部選配",
            "數量": int(local_projection.get("current_pending") or 0),
            "說明": "尚未扣除已偵測本機 defaults",
        },
        {
            "項目": "本機 defaults 可處理",
            "數量": int(local_projection.get("available_local_default_gap_count") or 0),
            "說明": local_capabilities,
        },
        {
            "項目": "有效剩餘",
            "數量": int(local_projection.get("remaining_pending") or 0),
            "說明": remaining_capabilities,
        },
        {
            "項目": "有效 blocking",
            "數量": int(local_projection.get("remaining_blocking_pending") or 0),
            "說明": "正式部署前必修缺口",
        },
        {
            "項目": "有效選配",
            "數量": int(local_projection.get("remaining_optional_pending") or 0),
            "說明": "依需求或合約再啟用",
        },
        {
            "項目": "付費外部 API",
            "數量": int(local_projection.get("remaining_paid_external_pending") or 0),
            "說明": remaining_capabilities,
        },
    ]
    commands = local_projection.get("local_default_verify_commands")
    if isinstance(commands, list) and commands:
        rows.append(
            {
                "項目": "本機驗證指令",
                "數量": len(commands),
                "說明": "\n".join(str(command) for command in commands if str(command).strip()),
            }
        )
    return rows


def maintenance_operation_rows(maintenance_operations: dict) -> list[dict]:
    operations = (
        maintenance_operations.get("operations")
        if isinstance(maintenance_operations.get("operations"), list)
        else []
    )
    return [
        {
            "操作": operation.get("label") or operation.get("id") or "-",
            "狀態": "需確認" if operation.get("requires_confirmation") else "可執行",
            "作用範圍": operation.get("scope") or "-",
            "可處理能力": _maintenance_operation_capability_summary(operation),
            "說明": operation.get("description") or "-",
            "指令": operation.get("display_command") or "-",
            "Timeout": int(operation.get("timeout_seconds") or 0),
        }
        for operation in operations
        if isinstance(operation, dict)
    ]


def maintenance_operation_post_run_check_rows(result: dict) -> list[dict]:
    checks = (
        result.get("post_run_checks") if isinstance(result.get("post_run_checks"), list) else []
    )
    return [
        {
            "項目": check.get("item") or "-",
            "用途": check.get("purpose") or "-",
            "可執行診斷": check.get("diagnostic_action_id") or "-",
            "指令": check.get("command") or "-",
        }
        for check in checks
        if isinstance(check, dict)
    ]


def maintenance_operation_post_run_diagnostic_action_ids(rows: list[dict]) -> list[str]:
    action_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        action_id = str(row.get("可執行診斷") or "").strip()
        if not action_id or action_id == "-" or action_id in seen:
            continue
        seen.add(action_id)
        action_ids.append(action_id)
    return action_ids


def recommended_maintenance_operation_id(
    maintenance_operations: dict,
    resolution_rows: list[dict],
    local_resolution_projection: dict | None = None,
) -> str:
    operation_ids = {
        str(operation.get("id") or "")
        for operation in maintenance_operations.get("operations") or []
        if isinstance(operation, dict)
        and operation.get("id")
        and operation.get("mutates_local_state")
    }
    projected_capabilities = _projection_local_action_capabilities(
        local_resolution_projection or {}
    )
    if projected_capabilities:
        if (
            "start_local_dependencies_with_unlocker" in operation_ids
            and "company_filing_high_risk_unlocker" in projected_capabilities
        ):
            return "start_local_dependencies_with_unlocker"
        if "start_local_dependencies" in operation_ids and projected_capabilities.intersection(
            {"neo4j_import", "graphrag_live_cypher_query"}
        ):
            return "start_local_dependencies"
    local_rows = [
        row
        for row in resolution_rows
        if isinstance(row, dict) and int(row.get("本機可套用") or 0) > 0
    ]
    if not local_rows:
        return ""
    local_text = "\n".join(
        str(row.get("本機指令") or row.get("建議動作") or "") for row in local_rows
    )
    if (
        "start_local_dependencies_with_unlocker" in operation_ids
        and "--prefer-unlocker" in local_text
    ):
        return "start_local_dependencies_with_unlocker"
    if "start_local_dependencies" in operation_ids:
        return "start_local_dependencies"
    return ""


def merge_local_action_projections(*projections: dict) -> dict:
    capabilities: list[str] = []
    seen: set[str] = set()
    for projection in projections:
        if not isinstance(projection, dict):
            continue
        for capability in _projection_local_action_capabilities(projection):
            if capability in seen:
                continue
            seen.add(capability)
            capabilities.append(capability)
    return {"local_action_capabilities": capabilities}


def maintenance_operation_recommendation_caption(
    maintenance_operations: dict,
    recommended_operation_id: str,
) -> str:
    if not recommended_operation_id:
        return ""
    operation = next(
        (
            item
            for item in maintenance_operations.get("operations") or []
            if isinstance(item, dict) and item.get("id") == recommended_operation_id
        ),
        {},
    )
    if not operation:
        return ""
    label = str(operation.get("label") or recommended_operation_id)
    command = str(operation.get("display_command") or "-")
    return f"建議操作：{label}；會預選此操作，確認後才會執行。指令：{command}"


def _projection_local_action_capabilities(local_resolution_projection: dict) -> set[str]:
    capabilities = local_resolution_projection.get("local_action_capabilities")
    if isinstance(capabilities, list):
        return {str(capability) for capability in capabilities if str(capability).strip()}
    local_defaults = local_resolution_projection.get("local_default_capabilities")
    if isinstance(local_defaults, list):
        return {
            str(row.get("capability") or "").strip()
            for row in local_defaults
            if isinstance(row, dict) and str(row.get("capability") or "").strip()
        }
    return set()


def _projection_capability_summary(value: object) -> str:
    if not isinstance(value, list):
        return "-"
    labels = []
    seen: set[str] = set()
    for row in value:
        if isinstance(row, dict):
            label = str(row.get("label") or row.get("capability") or "").strip()
        else:
            label = str(row or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return "、".join(labels) if labels else "-"


def _maintenance_operation_capability_summary(operation: dict) -> str:
    capabilities = operation.get("resolves_capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        return "-"
    labels = [
        str(row.get("label") or row.get("capability") or "").strip()
        for row in capabilities
        if isinstance(row, dict) and str(row.get("label") or row.get("capability") or "").strip()
    ]
    return "、".join(labels) if labels else "-"
