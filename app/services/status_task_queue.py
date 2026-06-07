from __future__ import annotations

from importlib import import_module
from typing import Any, Callable


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


def task_queue_status(
    settings: Any,
    *,
    redis_status: dict,
    redact_url: Callable[[str], str],
) -> dict:
    broker_url = str(getattr(settings, "redis_url", "") or "")
    export_status = _task_export_status()
    broker_ok = bool(redis_status.get("ok"))
    broker_configured = bool(broker_url.strip())
    submission_contract_ready = bool(
        export_status["task_export_namespace_available"]
        and export_status["celery_app_available"]
        and export_status["required_task_exports_present"]
        and export_status["task_names_match_expected"]
    )
    return {
        "collector_path": "app/services/status_task_queue.py",
        "ready": bool(broker_configured and broker_ok and submission_contract_ready),
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
        "smoke_commands": [
            ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping",
            ".venv/bin/python scripts/start_system.py --start-dependencies",
        ],
    }


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
    exported_tasks_present = {name: namespace.get(name) is not None for name in REQUIRED_TASK_EXPORTS}
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
    }
