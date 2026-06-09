from __future__ import annotations

from app.services.optimization_local_defaults import (
    AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND,
    local_default_capabilities,
    local_default_verify_commands,
    local_defaults_verify_command,
)


def local_resolution_projection(
    *,
    projected_status: str,
    local_resolvable_gap_count: int,
    projected_blocking_gap_count: int,
    projected_optional_gap_count: int,
    prioritized_next_actions: list[dict],
) -> dict:
    remaining_actions = [
        action for action in prioritized_next_actions if not bool(action.get("locally_available"))
    ]
    local_actions = [
        action for action in prioritized_next_actions if bool(action.get("locally_available"))
    ]
    local_defaults_command = local_defaults_verify_command(local_actions)
    local_default_commands = local_default_verify_commands(
        local_defaults_command,
        local_actions,
    )
    return {
        "status_after_local_defaults": projected_status,
        "local_resolvable_gap_count": local_resolvable_gap_count,
        "projected_blocking_gap_count": projected_blocking_gap_count,
        "projected_optional_gap_count": projected_optional_gap_count,
        "remaining_paid_external_pending": sum(
            1 for action in remaining_actions if action.get("action_type") == "paid_external"
        ),
        "local_defaults_verify_command": local_defaults_command,
        "compatible_auto_defaults_verify_command": AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND,
        "local_default_verify_commands": local_default_commands,
        "local_action_capabilities": [
            action.get("capability") for action in local_actions if action.get("capability")
        ],
        "local_default_capabilities": local_default_capabilities(local_actions),
        "remaining_action_capabilities": [
            action.get("capability") for action in remaining_actions if action.get("capability")
        ],
        "remaining_actions": remaining_actions,
        "next_action": _local_resolution_next_action(
            local_resolvable_gap_count=local_resolvable_gap_count,
            projected_blocking_gap_count=projected_blocking_gap_count,
            projected_optional_gap_count=projected_optional_gap_count,
        ),
    }


def progress_summary(
    *,
    overall_status: str,
    effective_status: str,
    total_domains: int,
    total_checks: int,
    ready_checks: int,
    completion_ratio: float,
    blocking_gap_count: int,
    optional_gap_count: int,
    local_resolvable_gap_count: int,
    effective_blocking_gap_count: int,
    effective_optional_gap_count: int,
    projected_blocking_gap_count: int,
    projected_optional_gap_count: int,
    primary_next_action: dict,
) -> dict:
    return {
        "status": overall_status,
        "effective_status_after_available_local_defaults": effective_status,
        "total_domains": total_domains,
        "total_checks": total_checks,
        "ready_checks": ready_checks,
        "completion_ratio": completion_ratio,
        "blocking_gap_count": blocking_gap_count,
        "optional_gap_count": optional_gap_count,
        "local_resolvable_gap_count": local_resolvable_gap_count,
        "effective_blocking_gap_count_after_available_local_defaults": (
            effective_blocking_gap_count
        ),
        "effective_optional_gap_count_after_available_local_defaults": (
            effective_optional_gap_count
        ),
        "projected_blocking_gap_count_after_local_defaults": (projected_blocking_gap_count),
        "projected_optional_gap_count_after_local_defaults": (projected_optional_gap_count),
        "primary_next_action_label": primary_next_action.get("label") or "",
        "primary_next_action_capability": primary_next_action.get("capability"),
        "primary_next_action_type": primary_next_action.get("action_type") or "",
        "primary_next_action_cost_profile": (primary_next_action.get("cost_profile") or ""),
        "primary_next_action_verify_command": (primary_next_action.get("verify_command") or ""),
    }


def primary_next_action(
    overall_status: str,
    next_actions: list[dict],
    *,
    optional_gap_count: int,
    local_resolvable_gap_count: int,
    projected_optional_gap_count: int,
    local_defaults_verify_command: str,
) -> dict:
    if overall_status == "degraded" and next_actions:
        return next_actions[0]
    if overall_status == "ready_with_optional_gaps":
        if local_resolvable_gap_count > 0:
            command = local_defaults_verify_command or AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND
            return {
                "domain_id": None,
                "domain_label": "全部",
                "capability": "auto_local_defaults",
                "label": "本機 defaults 可驗證",
                "status": "local_ready",
                "optional": True,
                "external": True,
                "action_type": "free_local_or_external_config",
                "locally_available": True,
                "priority_score": 75,
                "priority_band": "free_local_ready",
                "cost_profile": "free_local_available",
                "decision": "先用本機免費服務驗證；正式部署時再固化到 .env。",
                "priority_reason": "本機服務已偵測到，可用一條 audit 指令驗證多個選配缺口。",
                "verify_command": command,
                "next_action": (
                    f"先執行 `{command}`；可用本機 defaults "
                    f"驗證 {local_resolvable_gap_count} 項缺口，之後剩餘 "
                    f"{projected_optional_gap_count} 項外部/付費選配。"
                    f" 相容自動偵測入口：`{AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND}`。"
                ),
            }
        return {
            "domain_id": None,
            "domain_label": "全部",
            "capability": None,
            "label": "核心已完成",
            "status": "ready_with_optional_gaps",
            "optional": True,
            "external": True,
            "action_type": "optional_review",
            "next_action": (
                f"目前沒有 blocking 程式缺口；剩餘 {optional_gap_count} 項依正式部署、"
                "額度或付費資料源需求再啟用。"
            ),
        }
    return no_gap_action()


def effective_gap_count(
    *,
    raw_count: int,
    projected_count: int,
    local_resolvable_gap_count: int,
) -> int:
    if local_resolvable_gap_count > 0:
        return int(projected_count)
    return int(raw_count)


def effective_gap_note(
    *,
    raw_blocking_gap_count: int,
    raw_optional_gap_count: int,
    effective_blocking_gap_count: int,
    effective_optional_gap_count: int,
    local_resolvable_gap_count: int,
) -> str:
    if local_resolvable_gap_count <= 0:
        return ""
    return (
        f"原始缺口為 {raw_blocking_gap_count} blocking / {raw_optional_gap_count} 選配；"
        f"本機 defaults 可驗證 {local_resolvable_gap_count} 項後，"
        f"有效剩餘 {effective_blocking_gap_count} blocking / "
        f"{effective_optional_gap_count} 選配。"
    )


def status_note(status: str) -> str:
    if status == "degraded":
        return "仍有核心實作或設定缺口，需要先處理 blocking gaps。"
    if status == "ready_with_optional_gaps":
        return "核心實作已就緒；剩餘項目屬於外部部署、額度或付費資料源選配。"
    return "核心實作與已選定的外部能力都已就緒。"


def no_gap_action() -> dict:
    return {
        "domain_id": None,
        "domain_label": "全部",
        "capability": None,
        "label": "無立即缺口",
        "status": "ready",
        "optional": False,
        "external": False,
        "action_type": "monitoring",
        "next_action": "目前沒有需要立即改程式的缺口；維持 audit、報告觀測與額度監控即可。",
    }


def ratio(ready: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(ready / total, 4)


def _local_resolution_next_action(
    *,
    local_resolvable_gap_count: int,
    projected_blocking_gap_count: int,
    projected_optional_gap_count: int,
) -> str:
    if local_resolvable_gap_count <= 0:
        return "沒有偵測到可用本機 defaults；依一般優先隊列處理剩餘缺口。"
    if projected_blocking_gap_count == 0 and projected_optional_gap_count == 0:
        return (
            f"套用本機 defaults 可消除 {local_resolvable_gap_count} 項剩餘缺口；"
            "之後只需維持 smoke/audit 觀測。"
        )
    if projected_blocking_gap_count == 0:
        return (
            f"套用本機 defaults 可先消除 {local_resolvable_gap_count} 項缺口；"
            f"之後剩餘 {projected_optional_gap_count} 項外部/付費選配。"
        )
    return (
        f"套用本機 defaults 可先消除 {local_resolvable_gap_count} 項缺口；"
        f"仍有 {projected_blocking_gap_count} 項 blocking gap 需要處理。"
    )
