from __future__ import annotations

from app.services.external_deployment_enablement import (
    external_deployment_enablement_profile,
    external_deployment_local_projection as external_deployment_local_projection,
    external_deployment_pending_gap_action_counts as external_deployment_pending_gap_action_counts,
    external_enablement_group_entry as _external_enablement_group_entry,
    external_enablement_primary_next_action as _external_enablement_primary_next_action,
    external_enablement_summary_groups as _external_enablement_summary_groups,
    external_gap_action_label as _external_gap_action_label,
    external_gap_action_type as _external_gap_action_type,
    external_pending_gap_sort_key as _external_pending_gap_sort_key,
)
from app.services.external_deployment_items import (
    append_external_command as append_external_command,
    collect_external_smoke_commands as collect_external_smoke_commands,
    external_deployment_item_by_capability as external_deployment_item_by_capability,
    external_deployment_item_ready,
    external_deployment_readiness_items,
    external_deployment_readiness_metadata,
    external_deployment_warning_items,
    external_readiness_item_ready as _external_readiness_item_ready,
    external_smoke_commands_from_payload,
)
from app.services.external_deployment_local_dependencies import (
    local_dependency_last_start_rows as local_dependency_last_start_rows,
    local_dependency_port_state as _local_dependency_port_state,
    local_dependency_repair_rows as local_dependency_repair_rows,
    local_dependency_status_rows as local_dependency_status_rows,
)
from app.services.external_deployment_profiles import (
    EXTERNAL_DETAIL_KEYS,
    EXTERNAL_ENABLEMENT_METADATA as EXTERNAL_ENABLEMENT_METADATA,
    EXTERNAL_LOCAL_ACTION_METADATA,
    EXTERNAL_READINESS_METADATA as EXTERNAL_READINESS_METADATA,
    EXTERNAL_SMOKE_COMMAND_KEYS as EXTERNAL_SMOKE_COMMAND_KEYS,
)


def external_deployment_readiness_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for item in external_deployment_readiness_items(upgrade_audit):
        metadata = external_deployment_readiness_metadata(item)
        enablement = external_deployment_enablement_profile(item)
        local_action = external_deployment_local_action(
            item,
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
        rows.append(
            {
                "優先級": metadata["priority"],
                "項目": item.get("label") or item.get("capability") or "-",
                "狀態": external_deployment_readiness_state(item),
                "部署決策": external_deployment_readiness_decision(item),
                "啟用分類": enablement["group_label"],
                "免費驗證": enablement["free_validation_label"],
                "免費驗證指令": external_deployment_command_summary(
                    enablement["free_validation_commands"]
                ),
                "成本/額度": enablement["cost_label"],
                "建議路徑": enablement["recommended_path"],
                "本機動作": local_action["state"],
                "本機指令": local_action["command"],
                "影響範圍": metadata["impact"],
                "下一步": item.get("remediation") or "-",
                "驗證指令": external_deployment_command_summary(
                    external_smoke_commands_from_payload(item)
                ),
            }
        )
    return rows


def external_deployment_enablement_summary(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> dict:
    items = external_deployment_readiness_items(upgrade_audit)
    groups: dict[str, dict] = {}
    summary = {
        "total": len(items),
        "ready": 0,
        "pending": 0,
        "free_local_pending": 0,
        "local_action_available": 0,
        "quota_or_external_pending": 0,
        "paid_external_pending": 0,
        "manual_or_paid_pending": 0,
        "blocking_pending": 0,
        "nonblocking_optional_pending": 0,
        "all_pending_optional": False,
        "paid_external_only_pending": False,
        "groups": [],
        "primary_next_action": "",
    }
    for item in items:
        ready = external_deployment_item_ready(item)
        enablement = external_deployment_enablement_profile(item)
        local_action = external_deployment_local_action(
            item,
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
        group = _external_enablement_group_entry(groups, enablement)
        group["total"] += 1
        if ready:
            summary["ready"] += 1
            group["ready"] += 1
            continue

        summary["pending"] += 1
        group["pending"] += 1
        item_label = str(item.get("label") or item.get("capability") or "-")
        group["pending_items"].append(item_label)
        if item.get("optional") or item.get("_warning_source") == "optional_warnings":
            summary["nonblocking_optional_pending"] += 1
        else:
            summary["blocking_pending"] += 1
        deployment_profile = str(enablement.get("deployment_profile") or "")
        if deployment_profile == "free_local":
            summary["free_local_pending"] += 1
        elif deployment_profile == "paid_external":
            summary["paid_external_pending"] += 1
        else:
            summary["quota_or_external_pending"] += 1
        if local_action.get("state") in {
            "可啟動",
            "已啟動",
            "端口已啟動，需驗證",
            "驗證失敗",
        } and (local_action.get("command") != "-"):
            summary["local_action_available"] += 1

    summary["manual_or_paid_pending"] = (
        summary["quota_or_external_pending"] + summary["paid_external_pending"]
    )
    summary["all_pending_optional"] = bool(
        summary["pending"] > 0
        and summary["blocking_pending"] == 0
        and summary["nonblocking_optional_pending"] == summary["pending"]
    )
    summary["paid_external_only_pending"] = bool(
        summary["pending"] > 0
        and summary["paid_external_pending"] == summary["pending"]
        and summary["free_local_pending"] == 0
        and summary["quota_or_external_pending"] == 0
    )
    summary["groups"] = _external_enablement_summary_groups(groups)
    summary["primary_next_action"] = _external_enablement_primary_next_action(summary)
    return summary


def external_deployment_enablement_summary_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    summary = external_deployment_enablement_summary(
        upgrade_audit,
        local_dependency_status=local_dependency_status,
    )
    rows = []
    for group in summary.get("groups") or []:
        pending_items = [str(item) for item in group.get("pending_items") or []]
        rows.append(
            {
                "分類": group.get("label") or group.get("group") or "-",
                "待處理": int(group.get("pending") or 0),
                "已就緒": int(group.get("ready") or 0),
                "成本/額度": group.get("cost_label") or "-",
                "建議路徑": group.get("recommended_path") or "-",
                "待處理項目": "、".join(pending_items[:4]) if pending_items else "-",
            }
        )
    return rows


def external_deployment_pending_gap_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for item in external_deployment_readiness_items(upgrade_audit):
        if external_deployment_item_ready(item):
            continue
        metadata = external_deployment_readiness_metadata(item)
        enablement = external_deployment_enablement_profile(item)
        local_action = external_deployment_local_action(
            item,
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
        rows.append(
            {
                "priority": metadata["priority"],
                "area": str(item.get("area") or ""),
                "area_label": _external_area_label(item),
                "capability": str(item.get("capability") or ""),
                "label": str(item.get("label") or item.get("capability") or "-"),
                "status": str(item.get("status") or "-"),
                "severity": str(item.get("severity") or "warn"),
                "optional": bool(
                    item.get("optional") or item.get("_warning_source") == "optional_warnings"
                ),
                "decision": external_deployment_readiness_decision(item),
                "action_type": _external_gap_action_type(enablement, local_action),
                "deployment_profile": enablement["deployment_profile"],
                "enablement_group": enablement["group"],
                "enablement_label": enablement["group_label"],
                "free_local_available": enablement["free_local_available"],
                "free_validation_available": enablement["free_validation_available"],
                "free_validation_label": enablement["free_validation_label"],
                "free_validation_commands": enablement["free_validation_commands"],
                "paid_service_required": enablement["paid_service_required"],
                "local_action_state": local_action["state"],
                "local_action_command": local_action["command"],
                "cost_label": enablement["cost_label"],
                "recommended_path": enablement["recommended_path"],
                "remediation": item.get("remediation") or "-",
                "detail": _external_warning_detail(item),
                "smoke_commands": external_smoke_commands_from_payload(item),
            }
        )
    return sorted(rows, key=_external_pending_gap_sort_key)


def external_deployment_pending_gap_display_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    return [
        {
            "優先級": row["priority"],
            "能力": row["label"],
            "處理類型": _external_gap_action_label(row["action_type"]),
            "狀態": row["status"],
            "部署決策": row["decision"],
            "啟用分類": row["enablement_label"],
            "免費驗證": row["free_validation_label"],
            "免費驗證指令": external_deployment_command_summary(
                row["free_validation_commands"]
            ),
            "本機動作": row["local_action_state"],
            "本機指令": row["local_action_command"],
            "成本/額度": row["cost_label"],
            "建議路徑": row["recommended_path"],
        }
        for row in external_deployment_pending_gap_rows(
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
    ]


def external_deployment_local_action(
    item: dict,
    upgrade_audit: dict,
    *,
    local_dependency_status: dict | None = None,
) -> dict:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    metadata = EXTERNAL_LOCAL_ACTION_METADATA.get(key)
    if not metadata:
        return {
            "state": "已就緒" if item.get("severity") == "pass" else "需外部設定",
            "command": "-",
        }
    wait_status = (
        upgrade_audit.get("local_dependency_wait") if isinstance(upgrade_audit, dict) else {}
    )
    wait_status = wait_status if isinstance(wait_status, dict) else {}
    wait_key = str(metadata.get("wait_key") or "")
    verify_command = str(metadata.get("verify_command") or "-")
    item_ready = _external_readiness_item_ready(item)
    if wait_key and wait_key in wait_status:
        return {
            "state": _external_local_ready_state(item_ready)
            if wait_status.get(wait_key) is True
            else "驗證失敗",
            "command": verify_command,
        }
    port_state = _local_dependency_port_state(local_dependency_status, wait_key)
    if port_state is True:
        return {"state": _external_local_ready_state(item_ready), "command": verify_command}
    if item_ready:
        return {"state": "已啟動", "command": verify_command}
    return {
        "state": "可啟動",
        "command": str(metadata.get("start_command") or verify_command or "-"),
    }


def _external_local_ready_state(item_ready: bool) -> str:
    return "已啟動" if item_ready else "端口已啟動，需驗證"


def external_deployment_readiness_state(item: dict) -> str:
    severity = str(item.get("severity") or "")
    if severity == "pass":
        return "Ready"
    if severity == "fail":
        return "阻塞"
    if item.get("optional") or item.get("_warning_source") == "optional_warnings":
        return "外部選配"
    if severity == "warn":
        return "待配置"
    return str(item.get("status") or "-")


def external_deployment_readiness_decision(item: dict) -> str:
    severity = str(item.get("severity") or "")
    if severity == "pass":
        return "已就緒"
    if severity == "fail":
        return "正式部署前必修"
    if item.get("optional") or item.get("_warning_source") == "optional_warnings":
        return "需要該能力時配置"
    if severity == "warn":
        return "建議優先處理"
    return "檢查"


def external_deployment_command_summary(commands: list[str]) -> str:
    if not commands:
        return "-"
    if len(commands) == 1:
        return commands[0]
    return f"{commands[0]}\n另有 {len(commands) - 1} 個 smoke 指令，見下方單項診斷指令。"


def external_deployment_warning_rows(upgrade_audit: dict) -> list[dict]:
    rows: list[dict] = []
    for item in external_deployment_warning_items(upgrade_audit):
        enablement = external_deployment_enablement_profile(item)
        rows.append(
            {
                "面向": _external_area_label(item),
                "能力": item.get("label") or item.get("capability") or "-",
                "狀態": item.get("status") or "-",
                "警示層級": _external_warning_level(item),
                "啟用分類": enablement["group_label"],
                "成本/額度": enablement["cost_label"],
                "說明": _external_warning_detail(item),
                "診斷指令": "\n".join(external_smoke_commands_from_payload(item)) or "-",
                "處理方向": item.get("remediation") or "-",
            }
        )
    return rows


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
