from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

TASK_ASYNC_BRIDGE_OPERATIONS = (
    "celery.discovered_report",
    "celery.data_operation.",
    "celery.report_follow_up",
    "celery.generate_report.pre_report_refresh",
    "celery.after_close.refresh_data",
)

ALLOWED_APP_ASYNCIO_RUN_PATHS = {
    "app/core/async_bridge.py",
}

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
    "neo4j": (
        "COMPOSE_NEO4J_URI",
        "NEO4J_URI",
        "COMPOSE_NEO4J_USER",
        "NEO4J_USER",
        "COMPOSE_NEO4J_PASSWORD",
        "NEO4J_PASSWORD",
        "COMPOSE_NEO4J_DATABASE",
        "NEO4J_DATABASE",
        "COMPOSE_NEO4J_AUTH",
        "NEO4J_AUTH",
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


@dataclass(frozen=True)
class TaskQueueSourceDiagnostics:
    task_async_bridge: dict
    app_asyncio_run_policy: dict
    compose_runtime_env: dict


def task_queue_source_diagnostics() -> TaskQueueSourceDiagnostics:
    return TaskQueueSourceDiagnostics(
        task_async_bridge=_task_async_bridge_status(),
        app_asyncio_run_policy=_app_asyncio_run_policy_status(),
        compose_runtime_env=_compose_runtime_env_status(),
    )


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
        group: {key: _compose_env_key_present(compose_source, key) for key in keys}
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


def _compose_env_key_present(compose_source: str, key: str) -> bool:
    return f"{key}:" in compose_source or f"${{{key}" in compose_source


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


def _app_asyncio_run_policy_status() -> dict:
    repo_root = Path(__file__).resolve().parents[2]
    app_dir = repo_root / "app"
    paths = sorted(app_dir.rglob("*.py"))
    locations, parse_errors = _asyncio_run_call_locations(paths, root=repo_root)
    forbidden_locations = [
        location
        for location in locations
        if location["path"] not in ALLOWED_APP_ASYNCIO_RUN_PATHS
    ]
    ready = bool(not parse_errors and not forbidden_locations)
    return {
        "ready": ready,
        "scan_root": "app",
        "scan_file_count": len(paths),
        "allowed_paths": sorted(ALLOWED_APP_ASYNCIO_RUN_PATHS),
        "locations": locations,
        "forbidden_locations": forbidden_locations,
        "parse_errors": parse_errors,
        "fallback_reason": None if ready else "app_asyncio_run_policy_violation",
    }


def _asyncio_run_call_locations(paths: list[Path], *, root: Path) -> tuple[list[dict], list[dict]]:
    locations: list[dict] = []
    parse_errors: list[dict] = []
    for path in paths:
        relative_path = _relative_path(path, root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append(
                {
                    "path": relative_path,
                    "line": exc.lineno,
                    "error": exc.__class__.__name__,
                }
            )
            continue
        except OSError as exc:
            parse_errors.append(
                {
                    "path": relative_path,
                    "line": None,
                    "error": exc.__class__.__name__,
                }
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_asyncio_run_call(node.func):
                locations.append(
                    {
                        "path": relative_path,
                        "line": int(getattr(node, "lineno", 0) or 0),
                    }
                )
    return locations, parse_errors


def _is_asyncio_run_call(func: ast.AST) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "run"
        and isinstance(func.value, ast.Name)
        and func.value.id == "asyncio"
    )


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
