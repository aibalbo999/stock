from __future__ import annotations

from typing import Any

from app.services.optimization_domains import (
    OPTIMIZATION_DOMAINS,
    OptimizationCapabilityRef,
    OptimizationDomain,
)
from app.services.optimization_free_validation import capability_free_validation
from app.services.optimization_action_priority import (
    prioritized_optimization_next_actions,
)
from app.services.optimization_local_defaults import (
    AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND,
    EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND as EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND,
    EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND as EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND,
    LOCAL_BROWSER_RENDER_DEFAULTS_AUDIT_COMMAND as LOCAL_BROWSER_RENDER_DEFAULTS_AUDIT_COMMAND,
    LOCAL_FLARESOLVERR_DEFAULTS_AUDIT_COMMAND as LOCAL_FLARESOLVERR_DEFAULTS_AUDIT_COMMAND,
    LOCAL_NEO4J_DEFAULTS_AUDIT_COMMAND as LOCAL_NEO4J_DEFAULTS_AUDIT_COMMAND,
)
from app.services.optimization_progress_summary import (
    effective_gap_count,
    effective_gap_note,
    local_resolution_projection,
    primary_next_action,
    progress_summary,
    ratio,
    status_note,
)


READY_STATUSES = frozenset({"ready"})


def optimization_progress_status(status: dict) -> dict:
    matrix = status.get("upgrade_capability_matrix") or {}
    local_auto_defaults = _local_auto_defaults(status)
    domains = [
        _domain_status(domain, matrix, local_auto_defaults) for domain in OPTIMIZATION_DOMAINS
    ]
    blocking_gap_count = sum(int(domain["blocking_gap_count"]) for domain in domains)
    optional_gap_count = sum(int(domain["optional_gap_count"]) for domain in domains)
    local_resolvable_gap_count = sum(
        int(domain["local_resolvable_gap_count"]) for domain in domains
    )
    projected_blocking_gap_count = sum(
        int(domain["projected_blocking_gap_count"]) for domain in domains
    )
    projected_optional_gap_count = sum(
        int(domain["projected_optional_gap_count"]) for domain in domains
    )
    total_checks = sum(int(domain["total_checks"]) for domain in domains)
    ready_checks = sum(int(domain["ready_checks"]) for domain in domains)
    overall_status = _overall_status(blocking_gap_count, optional_gap_count)
    projected_status = _overall_status(
        projected_blocking_gap_count,
        projected_optional_gap_count,
    )
    effective_blocking_gap_count = effective_gap_count(
        raw_count=blocking_gap_count,
        projected_count=projected_blocking_gap_count,
        local_resolvable_gap_count=local_resolvable_gap_count,
    )
    effective_optional_gap_count = effective_gap_count(
        raw_count=optional_gap_count,
        projected_count=projected_optional_gap_count,
        local_resolvable_gap_count=local_resolvable_gap_count,
    )
    effective_status = projected_status if local_resolvable_gap_count > 0 else overall_status
    next_actions = _next_actions(domains)
    prioritized_next_actions = prioritized_optimization_next_actions(next_actions)
    local_projection = local_resolution_projection(
        projected_status=projected_status,
        local_resolvable_gap_count=local_resolvable_gap_count,
        projected_blocking_gap_count=projected_blocking_gap_count,
        projected_optional_gap_count=projected_optional_gap_count,
        prioritized_next_actions=prioritized_next_actions,
    )
    primary_action = primary_next_action(
        overall_status,
        prioritized_next_actions,
        optional_gap_count=optional_gap_count,
        local_resolvable_gap_count=local_resolvable_gap_count,
        projected_optional_gap_count=projected_optional_gap_count,
        local_defaults_verify_command=str(
            local_projection.get("local_defaults_verify_command") or ""
        ),
    )
    completion_ratio = ratio(ready_checks, total_checks)
    return {
        "collector_path": "app/services/optimization_progress.py",
        "status": overall_status,
        "projected_status_after_local_defaults": projected_status,
        "total_domains": len(domains),
        "total_checks": total_checks,
        "ready_checks": ready_checks,
        "blocking_gap_count": blocking_gap_count,
        "optional_gap_count": optional_gap_count,
        "local_resolvable_gap_count": local_resolvable_gap_count,
        "effective_status_after_available_local_defaults": effective_status,
        "effective_blocking_gap_count_after_available_local_defaults": (
            effective_blocking_gap_count
        ),
        "effective_optional_gap_count_after_available_local_defaults": (
            effective_optional_gap_count
        ),
        "projected_blocking_gap_count_after_local_defaults": projected_blocking_gap_count,
        "projected_optional_gap_count_after_local_defaults": projected_optional_gap_count,
        "completion_ratio": completion_ratio,
        "summary": progress_summary(
            overall_status=overall_status,
            effective_status=effective_status,
            total_domains=len(domains),
            total_checks=total_checks,
            ready_checks=ready_checks,
            completion_ratio=completion_ratio,
            blocking_gap_count=blocking_gap_count,
            optional_gap_count=optional_gap_count,
            local_resolvable_gap_count=local_resolvable_gap_count,
            effective_blocking_gap_count=effective_blocking_gap_count,
            effective_optional_gap_count=effective_optional_gap_count,
            projected_blocking_gap_count=projected_blocking_gap_count,
            projected_optional_gap_count=projected_optional_gap_count,
            primary_next_action=primary_action,
        ),
        "domains": domains,
        "primary_next_action": primary_action,
        "next_actions": next_actions,
        "prioritized_next_actions": prioritized_next_actions,
        "local_defaults_verify_command": (
            local_projection.get("local_defaults_verify_command") or ""
        ),
        "local_default_verify_commands": (
            local_projection.get("local_default_verify_commands") or []
        ),
        "local_resolution_projection": local_projection,
        "status_note": status_note(overall_status),
        "effective_gap_note": effective_gap_note(
            raw_blocking_gap_count=blocking_gap_count,
            raw_optional_gap_count=optional_gap_count,
            effective_blocking_gap_count=effective_blocking_gap_count,
            effective_optional_gap_count=effective_optional_gap_count,
            local_resolvable_gap_count=local_resolvable_gap_count,
        ),
        "local_auto_defaults": _local_auto_defaults_summary(local_auto_defaults),
    }


def _domain_status(
    domain: OptimizationDomain,
    matrix: dict,
    local_auto_defaults: dict,
) -> dict:
    checks = [_capability_check(ref, matrix, local_auto_defaults) for ref in domain.capability_refs]
    ready_checks = sum(1 for check in checks if check["ready"])
    blocking_gaps = [check for check in checks if not check["ready"] and not check["optional"]]
    optional_gaps = [check for check in checks if not check["ready"] and check["optional"]]
    local_resolvable_gaps = [
        check for check in [*blocking_gaps, *optional_gaps] if check.get("locally_available")
    ]
    projected_blocking_gaps = [
        check for check in blocking_gaps if not check.get("locally_available")
    ]
    projected_optional_gaps = [
        check for check in optional_gaps if not check.get("locally_available")
    ]
    domain_status = _overall_status(len(blocking_gaps), len(optional_gaps))
    projected_status = _overall_status(
        len(projected_blocking_gaps),
        len(projected_optional_gaps),
    )
    return {
        "id": domain.id,
        "label": domain.label,
        "objective": domain.objective,
        "status": domain_status,
        "projected_status_after_local_defaults": projected_status,
        "total_checks": len(checks),
        "ready_checks": ready_checks,
        "blocking_gap_count": len(blocking_gaps),
        "optional_gap_count": len(optional_gaps),
        "local_resolvable_gap_count": len(local_resolvable_gaps),
        "projected_blocking_gap_count": len(projected_blocking_gaps),
        "projected_optional_gap_count": len(projected_optional_gaps),
        "completion_ratio": ratio(ready_checks, len(checks)),
        "checks": checks,
        "blocking_gaps": blocking_gaps,
        "optional_gaps": optional_gaps,
        "local_resolvable_gaps": local_resolvable_gaps,
        "projected_remaining_gaps": [*projected_blocking_gaps, *projected_optional_gaps],
        "next_action": _domain_next_action(domain, blocking_gaps, optional_gaps),
        "long_term_note": domain.long_term_note,
    }


def _capability_check(
    ref: OptimizationCapabilityRef,
    matrix: dict,
    local_auto_defaults: dict,
) -> dict:
    capability = _matrix_capability(matrix, ref.area, ref.capability)
    capability_status = str(capability.get("status") or "missing")
    ready = capability_status in READY_STATUSES
    local_match = _local_auto_default_match(ref, local_auto_defaults)
    locally_available = bool(local_match and not ready)
    free_validation = capability_free_validation(capability)
    return {
        "area": ref.area,
        "capability": ref.capability,
        "label": ref.label,
        "status": "local_ready" if locally_available else capability_status,
        "capability_status": capability_status,
        "ready": ready,
        "optional": ref.optional,
        "external": ref.external,
        "action_type": ref.action_type,
        "next_action": _next_action_for_capability(
            ref,
            capability,
            local_match=local_match,
            locally_available=locally_available,
        ),
        "detail": capability.get("detail"),
        "locally_available": locally_available,
        "local_auto_default": local_match or {},
        "free_validation_available": free_validation["available"],
        "free_validation_label": free_validation["label"],
        "free_validation_commands": free_validation["commands"],
    }


def _matrix_capability(matrix: dict, area: str, capability: str) -> dict:
    area_payload = matrix.get(area) if isinstance(matrix.get(area), dict) else {}
    payload = area_payload.get(capability) if isinstance(area_payload.get(capability), dict) else {}
    return payload


def _domain_next_action(
    domain: OptimizationDomain,
    blocking_gaps: list[dict],
    optional_gaps: list[dict],
) -> str:
    if blocking_gaps:
        return str(blocking_gaps[0]["next_action"])
    if optional_gaps:
        return str(optional_gaps[0]["next_action"])
    if domain.long_term_note:
        return domain.long_term_note
    return "目前沒有需要立即改程式的缺口；以觀測、額度與資料品質回歸檢查為主。"


def _next_actions(domains: list[dict]) -> list[dict]:
    actions: list[dict] = []
    for domain in domains:
        for gap_type in ("blocking_gaps", "optional_gaps"):
            for gap in domain.get(gap_type) or []:
                actions.append(
                    {
                        "domain_id": domain["id"],
                        "domain_label": domain["label"],
                        "capability": gap["capability"],
                        "label": gap["label"],
                        "status": gap["status"],
                        "optional": gap["optional"],
                        "external": gap["external"],
                        "action_type": gap["action_type"],
                        "next_action": gap["next_action"],
                        "capability_status": gap.get("capability_status"),
                        "locally_available": gap.get("locally_available"),
                        "local_auto_default": gap.get("local_auto_default") or {},
                        "free_validation_available": bool(gap.get("free_validation_available")),
                        "free_validation_label": gap.get("free_validation_label") or "",
                        "free_validation_commands": gap.get("free_validation_commands") or [],
                    }
                )
    return actions


def _next_action_for_capability(
    ref: OptimizationCapabilityRef,
    capability: dict[str, Any],
    *,
    local_match: dict | None,
    locally_available: bool,
) -> str:
    if locally_available and local_match:
        command = str(local_match.get("verify_command") or AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND)
        group = str(local_match.get("group") or "local dependency")
        return (
            f"本機 {group} 服務已偵測到；可先用 `{command}` 驗證並套用本次程序 defaults，"
            "正式部署時再寫入 .env。"
        )
    return ref.next_action or _default_next_action(ref, capability)


def _default_next_action(ref: OptimizationCapabilityRef, capability: dict[str, Any]) -> str:
    detail = str(capability.get("detail") or "").strip()
    if detail:
        return f"檢查 {ref.label}：{detail}"
    return f"檢查 {ref.label} 的設定、依賴與測試證據。"


def _overall_status(blocking_gap_count: int, optional_gap_count: int) -> str:
    if blocking_gap_count:
        return "degraded"
    if optional_gap_count:
        return "ready_with_optional_gaps"
    return "ready"


def _local_auto_defaults(status: dict) -> dict:
    direct = status.get("local_dependency_auto_defaults")
    if isinstance(direct, dict):
        return direct
    local_dependencies = status.get("local_dependencies")
    if isinstance(local_dependencies, dict) and isinstance(
        local_dependencies.get("auto_defaults_preview"),
        dict,
    ):
        return local_dependencies["auto_defaults_preview"]
    return {}


def _local_auto_default_match(
    ref: OptimizationCapabilityRef,
    local_auto_defaults: dict,
) -> dict | None:
    if ref.action_type != "free_local_or_external_config":
        return None
    matches = local_auto_defaults.get("capability_matches")
    if not isinstance(matches, list):
        return None
    for match in matches:
        if not isinstance(match, dict):
            continue
        if match.get("area") == ref.area and match.get("capability") == ref.capability:
            return match
    return None


def _local_auto_defaults_summary(local_auto_defaults: dict) -> dict:
    if not local_auto_defaults:
        return {}
    return {
        "mode": local_auto_defaults.get("mode"),
        "compatible_audit_command": local_auto_defaults.get("compatible_audit_command"),
        "detected": local_auto_defaults.get("detected") or {},
        "would_apply_groups": local_auto_defaults.get("would_apply_groups") or [],
        "already_configured_groups": local_auto_defaults.get("already_configured_groups") or [],
        "local_action_available_count": int(
            local_auto_defaults.get("local_action_available_count") or 0
        ),
    }
