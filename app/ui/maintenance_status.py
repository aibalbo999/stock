from __future__ import annotations

from html import escape

from app.services.candidate_confidence import format_confidence_score


def maintenance_service_metrics(status: dict, service_snapshot: dict) -> dict:
    confidence = service_snapshot.get("candidate_confidence") or {}
    high_threshold = confidence.get("high_threshold")
    task_queue = service_snapshot.get("task_queue") or {}
    return {
        "資料庫": "正常" if status.get("integrity", {}).get("ok", True) else "異常",
        "Redis": "正常" if service_snapshot.get("redis", {}).get("ok") else "未連線",
        "背景任務": _task_queue_label(task_queue),
        "AI Key": service_snapshot.get("gemini", {}).get("key_count", 0),
        "市場資料": "可用" if service_snapshot.get("finmind", {}).get("mode") else "檢查",
        "升格門檻": format_confidence_score(float(high_threshold)) if high_threshold is not None else "未評估",
    }


def _task_queue_label(task_queue: dict) -> str:
    if not task_queue.get("ready"):
        return "檢查"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "可排隊"
    return "可送出"


def upgrade_audit_html(audit: dict) -> str:
    summary = audit.get("summary") or {}
    status = str(audit.get("overall_status") or "unknown")
    implementation = audit.get("implementation") or {}
    deployment = audit.get("deployment") or {}
    implementation_status = str(
        implementation.get("status") or summary.get("implementation_status") or "unknown"
    )
    deployment_status = str(deployment.get("status") or summary.get("deployment_status") or "unknown")
    status_labels = {
        "ready": "通過",
        "caution": "注意",
        "failed": "需處理",
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
            整體狀態：{status_label}；核心 {implementation_ready}/{implementation_total} 通過，外部 {deployment_ready}/{deployment_total} 通過；注意 {warnings} 項、外部選配 {optional_warnings} 項、需處理 {failures} 項。
        </div>
        <div class="upgrade-audit-areas">{areas}</div>
    </div>
    """.format(
        status_label=escape(status_labels.get(status, status)),
        implementation_status_class=escape(
            implementation_status if implementation_status in {"ready", "caution", "failed"} else "unknown"
        ),
        implementation_status_label=escape(status_labels.get(implementation_status, implementation_status)),
        deployment_status_class=escape(
            deployment_status if deployment_status in {"ready", "caution", "failed"} else "unknown"
        ),
        deployment_status_label=escape(status_labels.get(deployment_status, deployment_status)),
        strict_label=escape(strict_label),
        ready=ready,
        total=total,
        implementation_ready=implementation_ready,
        implementation_total=implementation_total,
        deployment_ready=deployment_ready,
        deployment_total=deployment_total,
        warnings=warnings,
        optional_warnings=optional_warnings,
        failures=failures,
        areas="".join(area_cards) or "<div class='upgrade-audit-area'><strong>未評估</strong><span>尚無稽核資料</span></div>",
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
