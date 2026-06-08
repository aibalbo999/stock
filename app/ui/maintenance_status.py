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


def task_queue_health_rows(service_snapshot: dict) -> list[dict]:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    return [
        {
            "項目": "Queue 提交",
            "狀態": _task_queue_label(task_queue),
            "說明": _task_queue_submission_detail(task_queue),
        },
        {
            "項目": "Redis Broker",
            "狀態": _ok_label(task_queue.get("broker_ok")),
            "說明": _connection_detail(task_queue, "broker_url"),
        },
        {
            "項目": "Redis Backend",
            "狀態": _ok_label(task_queue.get("backend_ok")),
            "說明": _connection_detail(task_queue, "backend_url"),
        },
        {
            "項目": "Task wiring",
            "狀態": "正常" if task_queue.get("submission_contract_ready") else "檢查",
            "說明": _task_wiring_detail(task_queue),
        },
        {
            "項目": "Celery Worker",
            "狀態": _worker_label(task_queue),
            "說明": _worker_detail(task_queue),
        },
    ]


def task_queue_health_alert(service_snapshot: dict) -> dict | None:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    if not task_queue:
        return {
            "severity": "warning",
            "message": "尚未取得 task_queue 狀態；請確認 /services/status 是否可讀取。",
        }
    if not task_queue.get("ready"):
        return {
            "severity": "error",
            "message": f"背景任務 queue 尚不可送出：{_task_queue_submission_detail(task_queue)}",
        }
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return {
            "severity": "warning",
            "message": "Queue 可收任務，但 Celery worker 未回應；任務可能停在佇列。",
        }
    if task_queue.get("worker_online"):
        worker_count = int(task_queue.get("worker_count") or 0)
        return {
            "severity": "success",
            "message": f"Queue 與 Celery worker 可用；目前 {worker_count} 個 worker 節點回應。",
        }
    return {
        "severity": "info",
        "message": "Queue 可送出；worker ping 尚未執行或被跳過。",
    }


def task_queue_smoke_command(service_snapshot: dict) -> str | None:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    commands = task_queue.get("smoke_commands")
    if isinstance(commands, list) and commands:
        return str(commands[0])
    return None


def task_failure_drilldown_rows(task_summary: dict) -> list[dict]:
    failures = _task_summary_failures(task_summary)
    return [
        {
            "run_id": row.get("id") or "-",
            "operation": row.get("operation") or "-",
            "status": row.get("status") or "-",
            "task_id": row.get("task_id") or "-",
            "category": row.get("error_category") or "-",
            "severity": row.get("error_severity") or "-",
            "summary": row.get("error_summary") or "-",
            "retry": "可重試" if row.get("retryable") else "需人工",
            "retry_kind": row.get("retry_kind") or "-",
            "next_action": row.get("next_action") or _fallback_failure_next_action(row),
            "next_steps": _task_next_steps_text(row),
            "error": row.get("error") or "-",
            "started_at": row.get("started_at") or "-",
        }
        for row in failures
    ]


def task_retry_options(task_summary: dict) -> list[dict]:
    options = []
    for row in _task_summary_failures(task_summary):
        task_id = str(row.get("task_id") or "").strip()
        if not task_id or not row.get("retryable"):
            continue
        options.append(
            {
                "task_id": task_id,
                "label": _task_retry_option_label(row),
                "operation": row.get("operation") or "unknown",
                "run_id": row.get("id"),
                "retry_endpoint": row.get("retry_endpoint") or f"POST /tasks/{task_id}/retry",
            }
        )
    return options


def _task_summary_failures(task_summary: dict) -> list[dict]:
    if not isinstance(task_summary, dict):
        return []
    failures = task_summary.get("recent_failures")
    if not isinstance(failures, list):
        return []
    return [row for row in failures if isinstance(row, dict)]


def _task_retry_option_label(row: dict) -> str:
    task_id = str(row.get("task_id") or "")
    operation = str(row.get("operation") or "unknown")
    run_id = row.get("id") or "-"
    return f"{operation}｜run #{run_id}｜{task_id}"


def _fallback_failure_next_action(row: dict) -> str:
    if row.get("task_id"):
        return "查看任務狀態，確認 payload 是否支援自動重試。"
    return "缺少 task id；請從 run 明細檢查。"


def _task_next_steps_text(row: dict) -> str:
    next_steps = row.get("next_steps")
    if not isinstance(next_steps, list):
        return "-"
    steps = [str(step).strip() for step in next_steps if str(step).strip()]
    return "；".join(steps) if steps else "-"


def _task_queue_from_snapshot(service_snapshot: dict) -> dict:
    if not isinstance(service_snapshot, dict):
        return {}
    task_queue = service_snapshot.get("task_queue")
    return task_queue if isinstance(task_queue, dict) else {}


def _ok_label(value: object) -> str:
    return "正常" if value else "檢查"


def _task_queue_submission_detail(task_queue: dict) -> str:
    if task_queue.get("ready"):
        if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
            return "Redis 與 task wiring 可送出；worker 未回應時任務會先留在 queue。"
        return "Redis broker/backend 與 Celery task wiring 已可提交。"
    issues = []
    if not task_queue:
        issues.append("尚未取得 task_queue 診斷")
    if not task_queue.get("broker_configured"):
        issues.append("Redis broker URL 未設定")
    if not task_queue.get("broker_ok"):
        issues.append("Redis broker 未連線")
    if not task_queue.get("backend_ok"):
        issues.append("Redis backend 未連線")
    if not task_queue.get("submission_contract_ready"):
        issues.append("Celery task exports 或 task name 尚未對齊")
    return "；".join(issues) or "狀態未知"


def _connection_detail(task_queue: dict, url_key: str) -> str:
    url = task_queue.get(url_key) or "-"
    redis_error = task_queue.get("redis_error")
    if redis_error:
        return f"{url}；Redis error: {redis_error}"
    return str(url)


def _task_wiring_detail(task_queue: dict) -> str:
    if task_queue.get("submission_contract_ready"):
        return "必要 Celery task exports 與 task name 已對齊。"
    missing = task_queue.get("missing_task_exports")
    if isinstance(missing, list) and missing:
        return "缺少 exports：" + "、".join(str(item) for item in missing)
    if task_queue.get("task_export_error"):
        return f"task export error: {task_queue['task_export_error']}"
    if task_queue.get("task_names_match_expected") is False:
        return "task name 與預期不一致。"
    return "尚未取得 task wiring 診斷。"


def _worker_label(task_queue: dict) -> str:
    if not task_queue.get("worker_ping_checked"):
        return "未檢查"
    if task_queue.get("worker_online"):
        return "在線"
    return "未回應"


def _worker_detail(task_queue: dict) -> str:
    if task_queue.get("worker_online"):
        nodes = task_queue.get("worker_nodes") or []
        if nodes:
            return "回應節點：" + "、".join(str(node) for node in nodes)
        return f"worker_count={int(task_queue.get('worker_count') or 0)}"
    if not task_queue.get("worker_ping_checked"):
        reason = task_queue.get("worker_ping_skipped_reason") or "worker ping 未執行"
        return f"未執行 ping：{reason}"
    details = ["worker ping 無回應"]
    if task_queue.get("worker_ping_error"):
        details.append(f"錯誤：{task_queue['worker_ping_error']}")
    timeout = task_queue.get("worker_ping_timeout_seconds")
    if timeout:
        details.append(f"timeout {timeout}s")
    return "；".join(details)


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
