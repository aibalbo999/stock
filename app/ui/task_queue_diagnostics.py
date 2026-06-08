from __future__ import annotations


def task_queue_label(task_queue: dict) -> str:
    if not task_queue.get("ready"):
        return "檢查"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "可排隊"
    return "可送出"


def task_queue_processing_label(task_queue: dict) -> str:
    if _task_queue_processing_ready(task_queue):
        return "可執行"
    if not task_queue.get("ready"):
        return "檢查"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "等待 worker"
    return "未確認"


def task_queue_health_rows(service_snapshot: dict) -> list[dict]:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    return [
        {
            "項目": "Queue 提交",
            "狀態": task_queue_label(task_queue),
            "說明": _task_queue_submission_detail(task_queue),
        },
        {
            "項目": "Queue 執行",
            "狀態": task_queue_processing_label(task_queue),
            "說明": _task_queue_processing_detail(task_queue),
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
    if _task_queue_processing_ready(task_queue):
        worker_count = int(task_queue.get("worker_count") or 0)
        return {
            "severity": "success",
            "message": f"Queue 與 Celery worker 可用；目前 {worker_count} 個 worker 節點回應。",
        }
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return {
            "severity": "warning",
            "message": "Queue 可收任務，但 Celery worker 未回應；任務可能停在佇列。",
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


def _task_queue_processing_detail(task_queue: dict) -> str:
    if _task_queue_processing_ready(task_queue):
        return "Queue 已可提交，且 Celery worker 可接手執行。"
    if not task_queue.get("ready"):
        return "Queue 尚不可提交，需先修復提交狀態。"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "Queue 可收任務，但 worker 未回應；任務會停在佇列直到 worker 上線。"
    return "Queue 可提交，但 worker ping 尚未執行；執行 readiness 未確認。"


def _task_queue_processing_ready(task_queue: dict) -> bool:
    if "processing_ready" in task_queue:
        return bool(task_queue.get("processing_ready"))
    return bool(task_queue.get("ready") and task_queue.get("worker_online"))


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
