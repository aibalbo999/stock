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


def optimization_progress_next_action_rows(progress: dict) -> list[dict]:
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
            "狀態": action.get("status") or "-",
            "能力狀態": action.get("capability_status") or action.get("status") or "-",
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
            "免費驗證指令": _action_free_validation_command_summary(action),
            "指令": _action_verify_command(action),
            "建議": action.get("next_action") or "-",
        }
        for action in actions
        if isinstance(action, dict)
    ]


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


def _action_free_validation_command_summary(action: dict) -> str:
    commands = _action_free_validation_commands(action)
    if not commands:
        return "-"
    return "\n".join(commands)


def _action_free_validation_commands(action: dict) -> list[str]:
    commands = action.get("free_validation_commands")
    if not isinstance(commands, list):
        return []
    return [str(command).strip() for command in commands if str(command).strip()]


def _format_progress_ratio(value: object) -> str:
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return "-"
