from __future__ import annotations

from app.services.external_deployment_items import external_smoke_commands_from_payload
from app.services.external_deployment_profiles import (
    EXTERNAL_ENABLEMENT_METADATA,
    EXTERNAL_LOCAL_ACTION_METADATA,
)


def external_deployment_enablement_profile(item: dict) -> dict:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    metadata = EXTERNAL_ENABLEMENT_METADATA.get(key, {})
    free_local_available = bool(metadata.get("free_local_available"))
    paid_service_required = bool(metadata.get("paid_service_required"))
    free_validation = _external_free_validation_profile(
        item,
        free_local_available=free_local_available,
    )
    return {
        "group": str(metadata.get("group") or "external_configuration"),
        "group_label": str(metadata.get("group_label") or "需外部設定"),
        "cost_profile": str(metadata.get("cost_profile") or "unknown"),
        "cost_label": str(metadata.get("cost_label") or "依外部服務設定而定"),
        "recommended_path": str(
            metadata.get("recommended_path") or item.get("remediation") or "-"
        ),
        "free_local_available": free_local_available,
        "free_validation_available": free_validation["available"],
        "free_validation_label": free_validation["label"],
        "free_validation_commands": free_validation["commands"],
        "paid_service_required": paid_service_required,
        "deployment_profile": (
            "free_local"
            if free_local_available and not paid_service_required
            else "paid_external"
            if paid_service_required
            else "quota_or_external"
        ),
    }


def external_deployment_pending_gap_action_counts(rows: list[dict]) -> dict[str, int]:
    counts = {
        "local_action": 0,
        "quota_or_external": 0,
        "paid_external": 0,
        "manual_configuration": 0,
    }
    for row in rows:
        action_type = str(row.get("action_type") or "manual_configuration")
        counts[action_type] = counts.get(action_type, 0) + 1
    return counts


def external_deployment_local_projection(
    pending_gaps: list[dict],
    local_dependency_auto_defaults: dict | None = None,
) -> dict:
    local_matches = _local_default_capability_matches(
        local_dependency_auto_defaults or {}
    )
    local_default_rows = [
        row
        for row in pending_gaps
        if (str(row.get("area") or ""), str(row.get("capability") or "")) in local_matches
    ]
    remaining_rows = [
        row
        for row in pending_gaps
        if (str(row.get("area") or ""), str(row.get("capability") or "")) not in local_matches
    ]
    remaining_action_counts = external_deployment_pending_gap_action_counts(remaining_rows)
    blocking_remaining = sum(1 for row in remaining_rows if not bool(row.get("optional")))
    optional_remaining = sum(1 for row in remaining_rows if bool(row.get("optional")))
    status_after_local_defaults = (
        "failed" if blocking_remaining else "caution" if optional_remaining else "ready"
    )
    local_commands = _local_default_projection_commands(local_default_rows, local_matches)
    return {
        "status_after_available_local_defaults": status_after_local_defaults,
        "current_pending": len(pending_gaps),
        "current_blocking_pending": sum(1 for row in pending_gaps if not bool(row.get("optional"))),
        "current_optional_pending": sum(1 for row in pending_gaps if bool(row.get("optional"))),
        "available_local_default_gap_count": len(local_default_rows),
        "remaining_pending": len(remaining_rows),
        "remaining_blocking_pending": blocking_remaining,
        "remaining_optional_pending": optional_remaining,
        "remaining_action_counts": remaining_action_counts,
        "remaining_paid_external_pending": int(remaining_action_counts.get("paid_external") or 0),
        "remaining_quota_or_external_pending": int(
            remaining_action_counts.get("quota_or_external") or 0
        ),
        "remaining_manual_configuration_pending": int(
            remaining_action_counts.get("manual_configuration") or 0
        ),
        "local_default_capabilities": _projection_capability_labels(local_default_rows),
        "remaining_capabilities": _projection_capability_labels(remaining_rows),
        "local_default_verify_commands": local_commands,
        "next_action": _external_deployment_local_projection_next_action(
            local_gap_count=len(local_default_rows),
            remaining_rows=remaining_rows,
            remaining_action_counts=remaining_action_counts,
        ),
    }


def external_enablement_group_entry(groups: dict[str, dict], enablement: dict) -> dict:
    group_key = str(enablement.get("group") or "external_configuration")
    if group_key not in groups:
        groups[group_key] = {
            "group": group_key,
            "label": str(enablement.get("group_label") or "需外部設定"),
            "cost_profile": str(enablement.get("cost_profile") or "unknown"),
            "cost_label": str(enablement.get("cost_label") or "依外部服務設定而定"),
            "recommended_path": str(enablement.get("recommended_path") or "-"),
            "free_local_available": bool(enablement.get("free_local_available")),
            "paid_service_required": bool(enablement.get("paid_service_required")),
            "deployment_profile": str(enablement.get("deployment_profile") or ""),
            "total": 0,
            "ready": 0,
            "pending": 0,
            "pending_items": [],
        }
    return groups[group_key]


def external_enablement_summary_groups(groups: dict[str, dict]) -> list[dict]:
    return [
        groups[key]
        for key in sorted(
            groups,
            key=lambda group_key: _external_enablement_group_sort_key(groups[group_key]),
        )
    ]


def external_enablement_primary_next_action(summary: dict) -> str:
    if int(summary.get("pending") or 0) <= 0:
        return "外部部署選配皆已就緒。"
    if int(summary.get("local_action_available") or 0) > 0:
        return "先處理本機免費可補強項目，再評估 API 額度或付費資料商。"
    if summary.get("paid_external_only_pending"):
        return "剩餘項目都是付費外部 API 或資料商選配；免費版可先維持範例資料檢查。"
    if int(summary.get("paid_external_pending") or 0) > 0:
        return "剩餘項目需要外部資料 API 或服務合約，免費版可先保留範例資料檢查。"
    if int(summary.get("quota_or_external_pending") or 0) > 0:
        return "剩餘項目主要取決於模型/API 額度，建議只在高價值文件啟用。"
    return "依啟用檢查清單逐項補齊設定。"


def external_gap_action_type(enablement: dict, local_action: dict) -> str:
    if (
        enablement.get("deployment_profile") == "free_local"
        and str(local_action.get("command") or "-") != "-"
    ):
        return "local_action"
    if enablement.get("paid_service_required"):
        return "paid_external"
    if enablement.get("deployment_profile") == "quota_or_external":
        return "quota_or_external"
    return "manual_configuration"


def external_gap_action_label(action_type: object) -> str:
    labels = {
        "local_action": "本機可修",
        "quota_or_external": "額度/外部選配",
        "paid_external": "付費外部 API",
        "manual_configuration": "手動設定",
    }
    return labels.get(str(action_type or ""), str(action_type or "-"))


def external_pending_gap_sort_key(row: dict) -> tuple[int, int, str]:
    action_order = {
        "local_action": 0,
        "quota_or_external": 1,
        "paid_external": 2,
        "manual_configuration": 3,
    }
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return (
        action_order.get(str(row.get("action_type") or ""), 4),
        priority_order.get(str(row.get("priority") or ""), 4),
        str(row.get("label") or ""),
    )


def _external_free_validation_profile(
    item: dict,
    *,
    free_local_available: bool = False,
) -> dict:
    if (
        str(item.get("area") or ""),
        str(item.get("capability") or ""),
    ) != ("data_business_logic", "company_filing_structured_api_fallback"):
        return _external_free_local_validation_profile(
            item,
            free_local_available=free_local_available,
        )
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else evidence
    free_validation = (
        runtime.get("free_validation")
        if isinstance(runtime.get("free_validation"), dict)
        else {}
    )
    sample_contract = (
        runtime.get("sample_contract")
        if isinstance(runtime.get("sample_contract"), dict)
        else {}
    )
    sample_ready = bool(
        free_validation.get("sample_contract_ready")
        or runtime.get("sample_contract_ready")
        or sample_contract.get("ready")
    )
    local_fixture_available = bool(
        free_validation.get("local_fixture_available")
        or runtime.get("local_fixture_http_smoke_cli")
        or runtime.get("local_fixture_provider_profile_smoke_cli")
        or runtime.get("local_fixture_start_cli")
        or runtime.get("local_fixture_smoke_cli")
    )
    provider_profile_smoke = (
        free_validation.get("local_fixture_provider_profile_smoke_cli")
        or runtime.get("local_fixture_provider_profile_smoke_cli")
    )
    commands = [
        free_validation.get("sample_contract_cli") or runtime.get("sample_contract_cli"),
        free_validation.get("local_fixture_http_smoke_cli")
        or runtime.get("local_fixture_http_smoke_cli"),
        provider_profile_smoke,
        free_validation.get("local_fixture_start_cli") or runtime.get("local_fixture_start_cli"),
        free_validation.get("local_fixture_smoke_cli") or runtime.get("local_fixture_smoke_cli"),
    ]
    command_texts = [str(command).strip() for command in commands if str(command or "").strip()]
    available = bool(sample_ready and local_fixture_available)
    return {
        "available": available,
        "label": "sample + fixture + provider profile 可驗證" if available else "-",
        "commands": command_texts,
    }


def _external_free_local_validation_profile(
    item: dict,
    *,
    free_local_available: bool,
) -> dict:
    if not free_local_available:
        return {"available": False, "label": "-", "commands": []}
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    local_metadata = EXTERNAL_LOCAL_ACTION_METADATA.get(key) or {}
    commands = [
        str(local_metadata.get("verify_command") or "").strip(),
        *external_smoke_commands_from_payload(item),
    ]
    command_texts: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if not command or command in seen:
            continue
        seen.add(command)
        command_texts.append(command)
    return {
        "available": bool(command_texts),
        "label": "本機 smoke 可驗證" if command_texts else "-",
        "commands": command_texts,
    }


def _external_enablement_group_sort_key(group: dict) -> tuple[int, str]:
    profile_order = {"free_local": 0, "quota_or_external": 1, "paid_external": 2}
    deployment_profile = str(group.get("deployment_profile") or "")
    return (
        profile_order.get(deployment_profile, 3),
        str(group.get("label") or group.get("group") or ""),
    )


def _local_default_capability_matches(local_dependency_auto_defaults: dict) -> dict[tuple[str, str], dict]:
    if not isinstance(local_dependency_auto_defaults, dict):
        return {}
    matches = {}
    for raw_match in local_dependency_auto_defaults.get("capability_matches") or []:
        if not isinstance(raw_match, dict):
            continue
        area = str(raw_match.get("area") or "").strip()
        capability = str(raw_match.get("capability") or "").strip()
        if not area or not capability:
            continue
        if not _local_default_match_available(raw_match):
            continue
        matches[(area, capability)] = raw_match
    return matches


def _local_default_match_available(match: dict) -> bool:
    state = str(match.get("state") or "").strip()
    return bool(match.get("would_apply") or match.get("configured") or state == "would_apply")


def _projection_capability_labels(rows: list[dict]) -> list[dict]:
    return [
        {
            "area": str(row.get("area") or ""),
            "capability": str(row.get("capability") or ""),
            "label": str(row.get("label") or row.get("capability") or ""),
            "action_type": str(row.get("action_type") or ""),
        }
        for row in rows
    ]


def _local_default_projection_commands(
    local_default_rows: list[dict],
    local_matches: dict[tuple[str, str], dict],
) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for row in local_default_rows:
        key = (str(row.get("area") or ""), str(row.get("capability") or ""))
        match = local_matches.get(key) or {}
        match_verify_command = str(match.get("verify_command") or "").strip()
        candidates = (
            [match_verify_command]
            if match_verify_command
            else [
                row.get("local_action_command"),
                *(row.get("free_validation_commands") or []),
            ]
        )
        for candidate in candidates:
            command = str(candidate or "").strip()
            if not command or command == "-" or command in seen:
                continue
            seen.add(command)
            commands.append(command)
    return commands


def _external_deployment_local_projection_next_action(
    *,
    local_gap_count: int,
    remaining_rows: list[dict],
    remaining_action_counts: dict[str, int],
) -> str:
    remaining_count = len(remaining_rows)
    paid_external = int(remaining_action_counts.get("paid_external") or 0)
    quota_or_external = int(remaining_action_counts.get("quota_or_external") or 0)
    manual_configuration = int(remaining_action_counts.get("manual_configuration") or 0)
    if local_gap_count <= 0:
        if remaining_count <= 0:
            return "外部部署選配皆已就緒。"
        if paid_external == remaining_count:
            return f"目前有效剩餘 {remaining_count} 項付費外部資料 API 選配。"
        if quota_or_external == remaining_count:
            return f"目前有效剩餘 {remaining_count} 項模型/API 額度或外部服務選配。"
        if manual_configuration == remaining_count:
            return f"目前有效剩餘 {remaining_count} 項手動設定。"
        return "沒有偵測到可套用的本機 defaults；依 pending gap 分類逐項處理。"
    if remaining_count <= 0:
        return f"套用已偵測本機 defaults 可消除 {local_gap_count} 項外部選配缺口。"
    if paid_external == remaining_count:
        return (
            f"套用已偵測本機 defaults 可先消除 {local_gap_count} 項缺口；"
            f"有效剩餘 {remaining_count} 項付費外部資料 API 選配。"
        )
    if quota_or_external == remaining_count:
        return (
            f"套用已偵測本機 defaults 可先消除 {local_gap_count} 項缺口；"
            f"有效剩餘 {remaining_count} 項模型/API 額度或外部服務選配。"
        )
    if manual_configuration == remaining_count:
        return (
            f"套用已偵測本機 defaults 可先消除 {local_gap_count} 項缺口；"
            f"有效剩餘 {remaining_count} 項手動設定。"
        )
    return (
        f"套用已偵測本機 defaults 可先消除 {local_gap_count} 項缺口；"
        f"有效剩餘 {remaining_count} 項外部部署選配。"
    )


__all__ = [
    "external_deployment_enablement_profile",
    "external_deployment_local_projection",
    "external_deployment_pending_gap_action_counts",
    "external_enablement_group_entry",
    "external_enablement_primary_next_action",
    "external_enablement_summary_groups",
    "external_gap_action_label",
    "external_gap_action_type",
    "external_pending_gap_sort_key",
]
