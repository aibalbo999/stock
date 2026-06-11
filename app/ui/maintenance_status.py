from __future__ import annotations

from html import escape

from app.services.candidate_confidence import format_confidence_score
from app.ui.task_queue_diagnostics import task_queue_label


def maintenance_service_metrics(status: dict, service_snapshot: dict) -> dict:
    confidence = service_snapshot.get("candidate_confidence") or {}
    high_threshold = confidence.get("high_threshold")
    task_queue = service_snapshot.get("task_queue") or {}
    return {
        "資料庫": "正常" if status.get("integrity", {}).get("ok", True) else "異常",
        "Redis": "正常" if service_snapshot.get("redis", {}).get("ok") else "未連線",
        "背景任務": task_queue_label(task_queue),
        "AI Key": service_snapshot.get("gemini", {}).get("key_count", 0),
        "市場資料": "可用" if service_snapshot.get("finmind", {}).get("mode") else "檢查",
        "升格門檻": format_confidence_score(float(high_threshold))
        if high_threshold is not None
        else "未評估",
    }


def upgrade_audit_html(audit: dict) -> str:
    summary = audit.get("summary") or {}
    status = str(audit.get("overall_status") or "unknown")
    implementation = audit.get("implementation") or {}
    deployment = audit.get("deployment") or {}
    implementation_status = str(
        implementation.get("status") or summary.get("implementation_status") or "unknown"
    )
    deployment_status = str(
        deployment.get("status") or summary.get("deployment_status") or "unknown"
    )
    deployment_blocking_status = str(
        deployment.get("blocking_status")
        or summary.get("deployment_blocking_status")
        or deployment_status
    )
    deployment_optional_only = bool(
        deployment.get("optional_only") or summary.get("deployment_optional_only")
    )
    deployment_display_status = "optional_only" if deployment_optional_only else deployment_status
    status_labels = {
        "ready": "通過",
        "caution": "注意",
        "failed": "需處理",
        "optional_only": "外部選配",
        "unknown": "未評估",
    }
    strict_label = "正式部署" if audit.get("strict_external") else "一般檢查"
    total = int(summary.get("total_checks") or 0)
    ready = int(summary.get("ready") or 0)
    warnings = int(summary.get("warnings") or 0)
    optional_warnings = int(summary.get("optional_warnings") or 0)
    failures = int(summary.get("failures") or 0)
    implementation_ready = int(implementation.get("ready") or 0)
    implementation_total = int(implementation.get("total_checks") or 0)
    deployment_ready = int(deployment.get("ready") or 0)
    deployment_total = int(deployment.get("total_checks") or 0)
    deployment_note = (
        "；外部目前只剩選配項目，沒有 blocking deployment 缺口" if deployment_optional_only else ""
    )
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    area_cards = []
    for area_key, area in sorted((audit.get("areas") or {}).items()):
        area_cards.append(
            '<div class="upgrade-audit-area"><strong>{label}</strong>'
            "<span>通過 {ready} / 注意 {warnings} / 需處理 {failures}</span></div>".format(
                label=escape(area_labels.get(area_key, str(area_key))),
                ready=int(area.get("ready") or 0),
                warnings=int(area.get("warnings") or 0),
                failures=int(area.get("failures") or 0),
            )
        )
    return """
    <div class="result-shell">
        <div class="section-title">升級稽核</div>
        <div class="upgrade-audit-grid">
            <div class="upgrade-audit-tile">
                <span>核心升級</span>
                <strong><span class="upgrade-audit-status {implementation_status_class}">{implementation_status_label}</span></strong>
            </div>
            <div class="upgrade-audit-tile">
                <span>外部整合</span>
                <strong><span class="upgrade-audit-status {deployment_status_class}">{deployment_status_label}</span></strong>
            </div>
            <div class="upgrade-audit-tile"><span>檢查模式</span><strong>{strict_label}</strong></div>
            <div class="upgrade-audit-tile"><span>通過項目</span><strong>{ready}/{total}</strong></div>
        </div>
        <div class="upgrade-audit-note">
            整體狀態：{status_label}；核心 {implementation_ready}/{implementation_total} 通過，外部 {deployment_ready}/{deployment_total} 通過，blocking {deployment_blocking_status}；注意 {warnings} 項、外部選配 {optional_warnings} 項、需處理 {failures} 項{deployment_note}。
        </div>
        <div class="upgrade-audit-areas">{areas}</div>
    </div>
    """.format(
        status_label=escape(status_labels.get(status, status)),
        implementation_status_class=escape(
            implementation_status
            if implementation_status in {"ready", "caution", "failed"}
            else "unknown"
        ),
        implementation_status_label=escape(
            status_labels.get(implementation_status, implementation_status)
        ),
        deployment_status_class=escape(
            deployment_status if deployment_status in {"ready", "caution", "failed"} else "unknown"
        ),
        deployment_status_label=escape(
            status_labels.get(deployment_display_status, deployment_display_status)
        ),
        strict_label=escape(strict_label),
        ready=ready,
        total=total,
        implementation_ready=implementation_ready,
        implementation_total=implementation_total,
        deployment_ready=deployment_ready,
        deployment_total=deployment_total,
        deployment_blocking_status=escape(
            status_labels.get(deployment_blocking_status, deployment_blocking_status)
        ),
        warnings=warnings,
        optional_warnings=optional_warnings,
        failures=failures,
        deployment_note=escape(deployment_note),
        areas="".join(area_cards)
        or "<div class='upgrade-audit-area'><strong>未評估</strong><span>尚無稽核資料</span></div>",
    )


def upgrade_audit_rows(audit: dict) -> list[dict]:
    severity_labels = {"pass": "通過", "warn": "注意", "fail": "需處理"}
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    return [
        {
            "面向": area_labels.get(str(check.get("area")), check.get("area")),
            "能力": check.get("label") or check.get("capability"),
            "結果": severity_labels.get(str(check.get("severity")), check.get("severity")),
            "目前狀態": check.get("status"),
            "說明": check.get("detail") or "-",
            "處理方向": check.get("remediation") or "-",
        }
        for check in audit.get("checks") or []
    ]


def optimization_progress_rows(progress: dict) -> list[dict]:
    status_labels = {
        "ready": "完成",
        "ready_with_optional_gaps": "核心完成/外部選配",
        "degraded": "需處理",
        "local_ready": "本機可驗證",
    }
    return [
        {
            "主題": domain.get("label") or domain.get("id") or "-",
            "狀態": status_labels.get(str(domain.get("status")), domain.get("status") or "-"),
            "完成": f"{int(domain.get('ready_checks') or 0)}/{int(domain.get('total_checks') or 0)}",
            "完成率": _format_progress_ratio(domain.get("completion_ratio")),
            "Blocking": int(domain.get("blocking_gap_count") or 0),
            "外部/選配": int(domain.get("optional_gap_count") or 0),
            "本機可補": int(domain.get("local_resolvable_gap_count") or 0),
            "套用後剩餘": (
                f"{int(domain.get('projected_blocking_gap_count') or 0)} blocking / "
                f"{int(domain.get('projected_optional_gap_count') or 0)} 選配"
            ),
            "下一步": domain.get("next_action") or "-",
            "長期考量": domain.get("long_term_note") or "-",
        }
        for domain in progress.get("domains") or []
        if isinstance(domain, dict)
    ]


def optimization_progress_metric_values(progress: dict) -> dict[str, object]:
    if not isinstance(progress, dict):
        progress = {}
    raw_status = str(progress.get("status") or "unknown")
    effective_status = str(
        progress.get("effective_status_after_available_local_defaults") or raw_status
    )
    raw_blocking = int(progress.get("blocking_gap_count") or 0)
    raw_optional = int(progress.get("optional_gap_count") or 0)
    effective_blocking = int(
        progress.get("effective_blocking_gap_count_after_available_local_defaults")
        if progress.get("effective_blocking_gap_count_after_available_local_defaults")
        is not None
        else raw_blocking
    )
    effective_optional = int(
        progress.get("effective_optional_gap_count_after_available_local_defaults")
        if progress.get("effective_optional_gap_count_after_available_local_defaults")
        is not None
        else raw_optional
    )
    return {
        "狀態": optimization_progress_status_label(effective_status),
        "狀態_delta": (
            f"原始 {optimization_progress_status_label(raw_status)}"
            if effective_status != raw_status
            else None
        ),
        "完成": f"{int(progress.get('ready_checks') or 0)}/{int(progress.get('total_checks') or 0)}",
        "Blocking": effective_blocking,
        "Blocking_delta": (
            f"原始 {raw_blocking}" if effective_blocking != raw_blocking else None
        ),
        "外部/選配": effective_optional,
        "外部/選配_delta": (
            f"原始 {raw_optional}" if effective_optional != raw_optional else None
        ),
        "本機可補": int(progress.get("local_resolvable_gap_count") or 0),
    }


def optimization_progress_status_label(status: object) -> str:
    status_labels = {
        "ready": "完成",
        "ready_with_optional_gaps": "核心完成/外部選配",
        "degraded": "需處理",
        "local_ready": "本機可驗證",
        "not_configured": "未設定",
        "unknown": "未評估",
    }
    text = str(status or "unknown")
    return status_labels.get(text, text)


def maintenance_overview_status_label(status: object) -> str:
    status_labels = {
        "ready": "可用",
        "ready_with_optional_gaps": "核心可用/外部選配",
        "caution": "需注意",
        "failed": "需處理",
        "blocked": "需處理",
        "degraded": "需處理",
        "not_configured": "未設定",
        "insufficient": "資料不足",
        "unknown": "未評估",
    }
    text = str(status or "unknown")
    return status_labels.get(text, text)


def optimization_progress_next_action_rows(
    progress: dict, *, compact: bool = False
) -> list[dict]:
    action_type_labels = {
        "code_or_config": "程式/設定",
        "free_local_or_external_config": "本機或外部設定",
        "paid_external": "付費外部 API",
        "quota_or_external": "額度/外部模型",
        "local_dependency": "本機依賴",
        "monitoring": "持續觀測",
        "optional_review": "選配審視",
    }
    cost_profile_labels = {
        "code_or_config": "程式/設定",
        "free_local_available": "本機免費可驗證",
        "free_local_or_external": "本機或外部",
        "local_dependency": "本機依賴",
        "quota_or_external": "額度/外部",
        "paid_external": "付費外部",
    }
    actions = progress.get("prioritized_next_actions") or progress.get("next_actions") or []
    primary_action = (
        progress.get("primary_next_action")
        if isinstance(progress.get("primary_next_action"), dict)
        else {}
    )
    if primary_action.get("capability") == "auto_local_defaults":
        actions = [primary_action, *actions]
    elif not actions and primary_action:
        actions = [primary_action]
    return [
        {
            "主題": action.get("domain_label") or "-",
            "能力": action.get("label") or action.get("capability") or "-",
            "優先分數": action.get("priority_score") or "-",
            "狀態": optimization_progress_status_label(action.get("status")),
            "能力狀態": optimization_progress_status_label(
                action.get("capability_status") or action.get("status")
            ),
            "本機": "可用" if action.get("locally_available") else "-",
            "類型": action_type_labels.get(
                str(action.get("action_type")),
                action.get("action_type") or "-",
            ),
            "成本/額度": cost_profile_labels.get(
                str(action.get("cost_profile")),
                action.get("cost_profile") or "-",
            ),
            "是否選配": "是" if action.get("optional") else "否",
            "是否外部": "是" if action.get("external") else "否",
            "決策": action.get("decision") or "-",
            "優先理由": action.get("priority_reason") or "-",
            "免費驗證": action.get("free_validation_label") or "-",
            "免費驗證指令": _action_free_validation_command_summary(
                action, compact=compact
            ),
            "指令": _action_verify_command(action),
            "建議": action.get("next_action") or "-",
        }
        for action in actions
        if isinstance(action, dict)
    ]


def optimization_progress_operator_summary(progress: dict) -> dict[str, str]:
    if not isinstance(progress, dict):
        progress = {}
    actions = _optimization_progress_actions(progress)
    blocking_count = int(progress.get("blocking_gap_count") or 0)
    optional_count = int(progress.get("optional_gap_count") or 0)
    local_count = int(progress.get("local_resolvable_gap_count") or 0)
    effective_optional = int(
        progress.get("effective_optional_gap_count_after_available_local_defaults")
        if progress.get("effective_optional_gap_count_after_available_local_defaults")
        is not None
        else optional_count
    )
    first_action = actions[0] if actions else {}
    local_action = _first_local_progress_action(actions)
    paid_external_action = _first_paid_external_progress_action(actions)
    paid_count = _paid_external_action_count(actions)

    if blocking_count:
        return {
            "state": "blocked",
            "title": "優化仍有 blocking 缺口",
            "detail": f"目前仍有 {blocking_count} 項 blocking 缺口；先處理必要能力，再看外部選配。",
            "local_action": f"先處理 {_action_label(first_action)}",
            "paid_external": "付費/API 選配不是優先事項",
            "next_step": _action_next_step(first_action, "先處理 blocking 缺口，再重跑升級稽核。"),
            "command": _action_verify_command(first_action) if first_action else "-",
        }

    if not optional_count and not actions:
        return {
            "state": "ready",
            "title": "優化目標目前沒有待處理缺口",
            "detail": "核心能力與外部部署檢查都沒有待處理項目。",
            "local_action": "不需本機 defaults",
            "paid_external": "付費/API 選配 0 項",
            "next_step": "維持例行 smoke、audit 與報告品質觀測。",
            "command": "-",
        }

    if optional_count and local_count <= 0 and paid_external_action:
        paid_label = _action_label(paid_external_action)
        return {
            "state": "ready",
            "title": "本機優化已完成，剩下外部資料 API 決策",
            "detail": (
                "目前沒有 blocking 缺口，也沒有本機 defaults 可補；"
                f"剩餘 {effective_optional or optional_count} 項是付費/API 選配。"
            ),
            "local_action": "本機 defaults 已無待處理項目",
            "paid_external": f"{paid_label}：需外部資料商或正式 API",
            "next_step": _action_next_step(
                paid_external_action,
                "若法說會簡報或重大訊息需要穩定資料，再設定 TEJ 或專業資料 API。",
            ),
            "command": "-",
        }

    local_label = _action_label(local_action)
    local_detail = (
        f"先驗證 {local_label}" if local_action else "目前沒有本機 defaults 可套用"
    )
    projection = (
        progress.get("local_resolution_projection")
        if isinstance(progress.get("local_resolution_projection"), dict)
        else {}
    )
    next_step = str(
        projection.get("next_action")
        or _action_next_step(first_action, "依下一步清單逐項處理。")
    )
    return {
        "state": "ready",
        "title": "核心優化已可用，先驗證本機選配",
        "detail": (
            f"目前沒有 blocking 缺口；{optional_count} 項外部選配中 "
            f"{local_count} 項可用本機 defaults 或免費 smoke 驗證。"
        ),
        "local_action": local_detail,
        "paid_external": f"付費/API 選配 {max(paid_count, effective_optional, 0)} 項可暫緩",
        "next_step": next_step,
        "command": _action_verify_command(local_action or first_action) if actions else "-",
    }


def optimization_progress_scope_summary(service_snapshot: dict) -> dict[str, str]:
    if not isinstance(service_snapshot, dict):
        return {}
    progress = (
        service_snapshot.get("optimization_progress")
        if isinstance(service_snapshot.get("optimization_progress"), dict)
        else {}
    )
    matrix = (
        service_snapshot.get("upgrade_capability_matrix")
        if isinstance(service_snapshot.get("upgrade_capability_matrix"), dict)
        else {}
    )
    if not progress or not matrix:
        return {}
    objective_refs = _optimization_objective_refs(progress)
    audit_checks = _upgrade_capability_checks(matrix)
    excluded = [
        check
        for check in audit_checks
        if (check["area"], check["capability"]) not in objective_refs
    ]
    objective_total = int(progress.get("total_checks") or len(objective_refs))
    objective_ready = int(progress.get("ready_checks") or 0)
    audit_total = len(audit_checks)
    audit_ready = sum(1 for check in audit_checks if check["status"] == "ready")
    if not excluded and audit_total == objective_total:
        return {}
    excluded_label = "、".join(_scope_check_label(check) for check in excluded) or "-"
    return {
        "state": "info",
        "title": "優化進度與升級稽核分母不同",
        "detail": (
            f"優化目標追蹤 {objective_total} 項；完整升級稽核追蹤 {audit_total} 項，"
            f"另含 {len(excluded)} 項部署 preflight。"
        ),
        "objective": f"優化目標 {objective_ready}/{objective_total}",
        "audit": f"升級稽核 {audit_ready}/{audit_total}",
        "excluded": f"部署 preflight：{excluded_label}",
        "note": "這不是缺口漏算；python_runtime 屬部署前檢查，不計入已核准的四大優化目標分母。",
    }


def _optimization_objective_refs(progress: dict) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for domain in progress.get("domains") or []:
        if not isinstance(domain, dict):
            continue
        for check in domain.get("checks") or []:
            if not isinstance(check, dict):
                continue
            area = str(check.get("area") or "").strip()
            capability = str(check.get("capability") or "").strip()
            if area and capability:
                refs.add((area, capability))
    return refs


def _upgrade_capability_checks(matrix: dict) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for area, capabilities in sorted(matrix.items()):
        if not isinstance(capabilities, dict):
            continue
        for capability, payload in sorted(capabilities.items()):
            if not isinstance(payload, dict):
                continue
            checks.append(
                {
                    "area": str(area),
                    "capability": str(capability),
                    "status": str(payload.get("status") or "unknown"),
                }
            )
    return checks


def _scope_check_label(check: dict[str, str]) -> str:
    labels = {
        ("architecture", "python_runtime"): "Python 3.11+ runtime",
    }
    key = (check.get("area") or "", check.get("capability") or "")
    return labels.get(key, check.get("capability") or "-")


def _action_verify_command(action: dict) -> str:
    verify_command = str(action.get("verify_command") or "").strip()
    if verify_command:
        return verify_command
    local_default = action.get("local_auto_default") or {}
    if isinstance(local_default, dict):
        local_command = str(local_default.get("verify_command") or "").strip()
        if local_command:
            return local_command
    free_commands = _action_free_validation_commands(action)
    if free_commands:
        return free_commands[0]
    return "-"


def _action_free_validation_command_summary(
    action: dict, *, compact: bool = False
) -> str:
    commands = _action_free_validation_commands(action)
    if not commands:
        return "-"
    if compact:
        return f"{len(commands)} 組免費 smoke"
    return "\n".join(commands)


def _action_free_validation_commands(action: dict) -> list[str]:
    commands = action.get("free_validation_commands")
    if not isinstance(commands, list):
        return []
    return [str(command).strip() for command in commands if str(command).strip()]


def _optimization_progress_actions(progress: dict) -> list[dict]:
    actions = progress.get("prioritized_next_actions") or progress.get("next_actions") or []
    primary_action = (
        progress.get("primary_next_action")
        if isinstance(progress.get("primary_next_action"), dict)
        else {}
    )
    if primary_action.get("capability") == "auto_local_defaults":
        actions = [primary_action, *actions]
    elif not actions and primary_action:
        actions = [primary_action]
    return [action for action in actions if isinstance(action, dict)]


def _first_local_progress_action(actions: list[dict]) -> dict:
    for action in actions:
        if action.get("locally_available") or action.get("cost_profile") in {
            "free_local_available",
            "free_local_or_external",
        }:
            return action
    return {}


def _first_paid_external_progress_action(actions: list[dict]) -> dict:
    for action in actions:
        if action.get("cost_profile") == "paid_external":
            return action
    return {}


def _paid_external_action_count(actions: list[dict]) -> int:
    return sum(1 for action in actions if action.get("cost_profile") == "paid_external")


def _action_label(action: dict) -> str:
    return str(action.get("label") or action.get("capability") or "下一個缺口")


def _action_next_step(action: dict, default: str) -> str:
    return str(action.get("next_action") or action.get("decision") or default)


def _format_progress_ratio(value: object) -> str:
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return "-"
