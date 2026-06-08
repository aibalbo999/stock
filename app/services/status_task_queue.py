from __future__ import annotations

from importlib import import_module
from typing import Any, Callable

from app.services.status_task_queue_sources import task_queue_source_diagnostics


REQUIRED_TASK_EXPORTS = (
    "celery_app",
    "generate_report_task",
    "discovered_report_task",
    "data_operation_task",
    "report_follow_up_task",
)

EXPECTED_TASK_NAMES = {
    "generate_report_task": "app.tasks.tasks.generate_report_task",
    "discovered_report_task": "app.tasks.tasks.discovered_report_task",
    "data_operation_task": "app.tasks.tasks.data_operation_task",
    "report_follow_up_task": "app.tasks.tasks.report_follow_up_task",
}
TASK_QUEUE_REPAIR_COMMANDS = {
    "inspect_ping": ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping",
    "start_dependencies": ".venv/bin/python scripts/start_system.py --start-dependencies",
    "start_worker": (
        ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app worker "
        "-B --loglevel=INFO --pool=solo"
    ),
    "upgrade_audit": ".venv/bin/python scripts/upgrade_audit.py",
}


def task_queue_status(
    settings: Any,
    *,
    redis_status: dict,
    redact_url: Callable[[str], str],
    worker_ping_func: Callable[[Any, float], dict | None] | None = None,
) -> dict:
    broker_url = str(getattr(settings, "redis_url", "") or "")
    export_status = _task_export_status()
    source_diagnostics = task_queue_source_diagnostics()
    async_bridge_status = source_diagnostics.task_async_bridge
    app_asyncio_run_policy_status = source_diagnostics.app_asyncio_run_policy
    compose_runtime_env_status = source_diagnostics.compose_runtime_env
    broker_ok = bool(redis_status.get("ok"))
    broker_configured = bool(broker_url.strip())
    worker_ping_timeout_seconds = max(
        0.1,
        float(getattr(settings, "task_queue_worker_ping_timeout_seconds", 1.0) or 1.0),
    )
    worker_ping_status = _worker_ping_status(
        export_status.get("_celery_app") if broker_ok else None,
        timeout_seconds=worker_ping_timeout_seconds,
        ping_func=worker_ping_func,
        skipped_reason=None if broker_ok else "broker_unavailable",
    )
    submission_contract_ready = bool(
        export_status["task_export_namespace_available"]
        and export_status["celery_app_available"]
        and export_status["required_task_exports_present"]
        and export_status["task_names_match_expected"]
    )
    ready = bool(broker_configured and broker_ok and submission_contract_ready)
    status = {
        "collector_path": "app/services/status_task_queue.py",
        "task_queue_source_diagnostics_extracted": source_diagnostics.__class__.__name__
        == "TaskQueueSourceDiagnostics"
        and async_bridge_status.get("path") == "app/tasks/tasks.py"
        and app_asyncio_run_policy_status.get("scan_root") == "app"
        and compose_runtime_env_status.get("path") == "docker-compose.yml",
        "task_queue_source_diagnostics_path": "app/services/status_task_queue_sources.py",
        "ready": ready,
        "processing_ready": bool(ready and worker_ping_status["worker_online"]),
        "submission_contract_ready": submission_contract_ready,
        "broker_configured": broker_configured,
        "broker_ok": broker_ok,
        "backend_ok": broker_ok,
        "broker_url": redact_url(broker_url),
        "backend_url": redact_url(broker_url),
        "redis_error": redis_status.get("error"),
        "required_task_exports": list(REQUIRED_TASK_EXPORTS),
        "exported_tasks_present": export_status["exported_tasks_present"],
        "missing_task_exports": export_status["missing_task_exports"],
        "celery_app_available": export_status["celery_app_available"],
        "celery_app_main": export_status["celery_app_main"],
        "task_names": export_status["task_names"],
        "expected_task_names": EXPECTED_TASK_NAMES,
        "task_names_match_expected": export_status["task_names_match_expected"],
        "task_export_namespace_available": export_status["task_export_namespace_available"],
        "task_export_error": export_status["task_export_error"],
        "task_async_bridge_guard_present": async_bridge_status["ready"],
        "task_async_bridge": async_bridge_status,
        "app_asyncio_run_policy_ready": app_asyncio_run_policy_status["ready"],
        "app_asyncio_run_policy": app_asyncio_run_policy_status,
        "compose_runtime_env_passthrough_ready": compose_runtime_env_status["ready"],
        "compose_runtime_env": compose_runtime_env_status,
        "worker_ping_checked": worker_ping_status["worker_ping_checked"],
        "worker_ping_timeout_seconds": worker_ping_timeout_seconds,
        "worker_online": worker_ping_status["worker_online"],
        "worker_count": worker_ping_status["worker_count"],
        "worker_nodes": worker_ping_status["worker_nodes"],
        "worker_ping_error": worker_ping_status["worker_ping_error"],
        "worker_ping_skipped_reason": worker_ping_status["worker_ping_skipped_reason"],
        "submission_endpoints": [
            "POST /reports/generate_async",
            "POST /pipeline/run_discovered_async",
            "POST /tasks/data-operation",
            "POST /reports/{report_id}/follow-up/run_async",
        ],
        "status_endpoints": [
            "GET /tasks/{task_id}",
            "GET /tasks/{task_id}/run",
            "GET /tasks/summary",
        ],
        "repair_commands": dict(TASK_QUEUE_REPAIR_COMMANDS),
        "smoke_commands": [
            TASK_QUEUE_REPAIR_COMMANDS["inspect_ping"],
            TASK_QUEUE_REPAIR_COMMANDS["start_dependencies"],
        ],
    }
    status["repair_plan"] = task_queue_repair_plan(status)
    return status


def task_queue_repair_plan(task_queue: dict) -> list[dict[str, str]]:
    commands = _task_queue_repair_commands(task_queue)
    verify_command = commands["inspect_ping"]
    if not task_queue:
        return [
            {
                "item": "Task queue 狀態",
                "state": "未取得",
                "next_step": "確認 API /services/status 可讀取，再重新整理維護頁。",
                "repair_command": "-",
                "verify_command": "curl -s http://127.0.0.1:8000/services/status",
                "severity": "warning",
            }
        ]
    rows: list[dict[str, str]] = []
    if not task_queue.get("broker_configured"):
        rows.append(
            {
                "item": "Redis 設定",
                "state": "未設定",
                "next_step": "設定 REDIS_URL，或使用一鍵啟動帶起本機 Redis。",
                "repair_command": commands["start_dependencies"],
                "verify_command": commands["upgrade_audit"],
                "severity": "error",
            }
        )
    if not task_queue.get("broker_ok") or not task_queue.get("backend_ok"):
        rows.append(
            {
                "item": "Redis Broker/Backend",
                "state": "未連線",
                "next_step": "啟動本機依賴後重新檢查 Redis broker/backend 連線。",
                "repair_command": commands["start_dependencies"],
                "verify_command": commands["upgrade_audit"],
                "severity": "error",
            }
        )
    if not task_queue.get("submission_contract_ready"):
        rows.append(
            {
                "item": "Celery task wiring",
                "state": "未對齊",
                "next_step": _task_wiring_detail(task_queue),
                "repair_command": commands["upgrade_audit"],
                "verify_command": commands["upgrade_audit"],
                "severity": "error",
            }
        )
    if task_queue.get("ready") and not _task_queue_processing_ready(task_queue):
        if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
            rows.append(
                {
                    "item": "Celery Worker",
                    "state": "未回應",
                    "next_step": "啟動 worker，或確認既有 worker 能連到同一個 Redis broker。",
                    "repair_command": commands["start_worker"],
                    "verify_command": verify_command,
                    "severity": "warning",
                }
            )
        elif not task_queue.get("worker_ping_checked"):
            rows.append(
                {
                    "item": "Celery Worker ping",
                    "state": "未檢查",
                    "next_step": "執行 inspect ping 確認是否有 worker 回應。",
                    "repair_command": verify_command,
                    "verify_command": verify_command,
                    "severity": "info",
                }
            )
    return rows


def _task_export_status() -> dict:
    namespace: dict[str, Any] = {}
    task_export_error = None
    try:
        module = import_module("app.api.task_exports")
        namespace_func = getattr(module, "task_export_namespace", None)
        if callable(namespace_func):
            namespace = namespace_func()
    except Exception as exc:
        task_export_error = str(exc)
    exported_tasks_present = {
        name: namespace.get(name) is not None for name in REQUIRED_TASK_EXPORTS
    }
    missing_task_exports = [name for name, present in exported_tasks_present.items() if not present]
    task_names = {
        name: str(getattr(namespace.get(name), "name", "") or "")
        for name in EXPECTED_TASK_NAMES
        if namespace.get(name) is not None
    }
    task_names_match_expected = all(
        task_names.get(name) == expected for name, expected in EXPECTED_TASK_NAMES.items()
    )
    celery_app = namespace.get("celery_app")
    return {
        "task_export_namespace_available": bool(namespace),
        "task_export_error": task_export_error,
        "exported_tasks_present": exported_tasks_present,
        "missing_task_exports": missing_task_exports,
        "required_task_exports_present": not missing_task_exports,
        "celery_app_available": celery_app is not None,
        "celery_app_main": str(getattr(celery_app, "main", "") or ""),
        "task_names": task_names,
        "task_names_match_expected": task_names_match_expected,
        "_celery_app": celery_app,
    }


def _task_queue_repair_commands(task_queue: dict) -> dict[str, str]:
    configured = task_queue.get("repair_commands") if isinstance(task_queue, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    return {
        key: str(configured.get(key) or default)
        for key, default in TASK_QUEUE_REPAIR_COMMANDS.items()
    }


def _task_queue_processing_ready(task_queue: dict) -> bool:
    if "processing_ready" in task_queue:
        return bool(task_queue.get("processing_ready"))
    return bool(task_queue.get("ready") and task_queue.get("worker_online"))


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


def _worker_ping_status(
    celery_app: Any,
    *,
    timeout_seconds: float,
    ping_func: Callable[[Any, float], dict | None] | None = None,
    skipped_reason: str | None = None,
) -> dict:
    if celery_app is None:
        return {
            "worker_ping_checked": False,
            "worker_online": False,
            "worker_count": 0,
            "worker_nodes": [],
            "worker_ping_error": None,
            "worker_ping_skipped_reason": skipped_reason or "celery_app_unavailable",
        }
    try:
        responses = (
            ping_func(celery_app, timeout_seconds)
            if ping_func is not None
            else _celery_inspect_ping(celery_app, timeout_seconds)
        ) or {}
    except Exception as exc:
        return {
            "worker_ping_checked": True,
            "worker_online": False,
            "worker_count": 0,
            "worker_nodes": [],
            "worker_ping_error": str(exc),
            "worker_ping_skipped_reason": None,
        }
    worker_nodes = sorted(str(node) for node in responses)
    return {
        "worker_ping_checked": True,
        "worker_online": bool(worker_nodes),
        "worker_count": len(worker_nodes),
        "worker_nodes": worker_nodes,
        "worker_ping_error": None,
        "worker_ping_skipped_reason": None,
    }


def _celery_inspect_ping(celery_app: Any, timeout_seconds: float) -> dict | None:
    inspector = celery_app.control.inspect(timeout=timeout_seconds)
    return inspector.ping()
