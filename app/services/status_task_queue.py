from __future__ import annotations

from importlib import import_module
from pathlib import Path
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

TASK_ASYNC_BRIDGE_OPERATIONS = (
    "celery.discovered_report",
    "celery.data_operation.",
    "celery.report_follow_up",
    "celery.generate_report.pre_report_refresh",
    "celery.after_close.refresh_data",
)

COMPOSE_RUNTIME_ENV_GROUPS = {
    "llm": (
        "LLM_PROVIDER",
        "PRIMARY_LLM_MODEL",
        "LOCAL_LLM_MODEL",
        "LLM_FALLBACK_MODELS",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEYS",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "COHERE_API_KEY",
        "LLM_MODEL_DAILY_REQUEST_BUDGETS",
        "LLM_MODEL_QUOTA_COOLDOWN_SECONDS",
    ),
    "rag": (
        "RAG_EMBEDDING_PROVIDER",
        "RAG_EMBEDDING_MODEL",
        "RAG_INDEX_SCHEMA_VERSION",
        "RAG_RERANKER_PROVIDER",
        "RAG_RERANKER_MODEL",
        "RAG_LLM_RERANKER_ENABLED",
    ),
    "company_filings": (
        "COMPANY_FILING_USER_AGENTS",
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
        "COMPANY_FILING_STRUCTURED_API_TOKEN",
        "COMPANY_FILING_VISUAL_RAG_ENABLED",
        "COMPANY_FILING_VISUAL_RAG_MODEL",
    ),
    "market_data": (
        "MARKET_PRICE_PROVIDER_ORDER",
        "FINMIND_TOKEN",
        "FUGLE_API_KEY",
    ),
    "observability": (
        "LLM_OBSERVABILITY_ENABLED",
        "LLM_OBSERVABILITY_PROVIDER",
        "LLM_OBSERVABILITY_EXTERNAL_DISPATCH_ENABLED",
        "LANGSMITH_API_KEY",
        "PHOENIX_ENDPOINT",
    ),
    "workflow": (
        "WORKFLOW_ENGINE",
        "WORKFLOW_LOCAL_FALLBACK_ENABLED",
        "PREFECT_API_URL",
        "TEMPORAL_ADDRESS",
        "TEMPORAL_TASK_QUEUE",
        "TEMPORAL_WORKFLOW_NAME",
        "AIRFLOW_API_URL",
        "AIRFLOW_DAG_ID",
        "AIRFLOW_API_TOKEN",
    ),
    "report_policy": (
        "AUTO_FOLLOW_UP_ENABLED",
        "SYNC_REPORT_PRE_REFRESH_ENABLED",
        "SYNC_REPORT_QUALITY_RECOVERY_ENABLED",
        "REPORT_QUALITY_AUTO_RECOVERY_ENABLED",
    ),
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
    async_bridge_status = _task_async_bridge_status()
    compose_runtime_env_status = _compose_runtime_env_status()
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
    return {
        "collector_path": "app/services/status_task_queue.py",
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
        "smoke_commands": [
            ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping",
            ".venv/bin/python scripts/start_system.py --start-dependencies",
        ],
    }


def _compose_runtime_env_status() -> dict:
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    try:
        compose_source = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "ready": False,
            "path": "docker-compose.yml",
            "required_groups": COMPOSE_RUNTIME_ENV_GROUPS,
            "present_groups": {},
            "missing_by_group": {},
            "fallback_reason": f"compose_source_unreadable:{exc.__class__.__name__}",
        }
    present_groups = {
        group: {key: f"{key}:" in compose_source for key in keys}
        for group, keys in COMPOSE_RUNTIME_ENV_GROUPS.items()
    }
    missing_by_group = {
        group: [key for key, present in rows.items() if not present]
        for group, rows in present_groups.items()
    }
    missing_by_group = {group: rows for group, rows in missing_by_group.items() if rows}
    celery_services_use_anchor = (
        "celery-worker:" in compose_source
        and "celery-beat:" in compose_source
        and "<<: *stock-ai-app" in compose_source
        and "environment: &stock-ai-env" in compose_source
    )
    ready = bool(celery_services_use_anchor and not missing_by_group)
    return {
        "ready": ready,
        "path": "docker-compose.yml",
        "celery_services_use_anchor": celery_services_use_anchor,
        "required_groups": COMPOSE_RUNTIME_ENV_GROUPS,
        "present_groups": present_groups,
        "missing_by_group": missing_by_group,
        "fallback_reason": None if ready else "compose_runtime_env_passthrough_incomplete",
    }


def _task_async_bridge_status() -> dict:
    tasks_path = Path(__file__).resolve().parents[1] / "tasks" / "tasks.py"
    try:
        tasks_source = tasks_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "ready": False,
            "path": "app/tasks/tasks.py",
            "fallback_reason": f"tasks_source_unreadable:{exc.__class__.__name__}",
        }
    operation_markers = {
        operation: operation in tasks_source
        for operation in TASK_ASYNC_BRIDGE_OPERATIONS
    }
    direct_asyncio_run_count = tasks_source.count("asyncio.run(")
    helper_imported = "from app.core.async_bridge import run_async_from_sync" in tasks_source
    return {
        "ready": bool(
            helper_imported
            and direct_asyncio_run_count == 0
            and all(operation_markers.values())
        ),
        "path": "app/tasks/tasks.py",
        "helper_imported": helper_imported,
        "direct_asyncio_run_count": direct_asyncio_run_count,
        "bridge_call_count": tasks_source.count("run_async_from_sync("),
        "operation_markers": operation_markers,
        "fallback_reason": None
        if helper_imported and direct_asyncio_run_count == 0 and all(operation_markers.values())
        else "missing_task_async_bridge_guard",
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
        "_celery_app": celery_app,
    }


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
