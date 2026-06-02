from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from importlib.util import find_spec
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings


SUPPORTED_WORKFLOW_ENGINES = {"local", "prefect", "temporal", "airflow"}


class WorkflowOrchestrationError(RuntimeError):
    def __init__(self, *, engine: str, reason: str) -> None:
        self.engine = engine
        self.reason = reason
        super().__init__(f"Workflow engine {engine} is not available: {reason}")


class WorkflowOrchestrationRunner:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any] = get_settings,
        status_provider: Callable[[Any], dict] | None = None,
        prefect_flow_runner: Callable[[str, Callable[[], Awaitable[dict]]], Awaitable[dict]] | None = None,
        temporal_dispatcher: Callable[[str, dict, Any], Awaitable[dict]] | None = None,
        airflow_dispatcher: Callable[[str, dict, Any], Awaitable[dict]] | None = None,
    ) -> None:
        self.settings_provider = settings_provider
        self.status_provider = status_provider or workflow_orchestration_status
        self.prefect_flow_runner = prefect_flow_runner or run_prefect_flow
        self.temporal_dispatcher = temporal_dispatcher or dispatch_temporal_workflow
        self.airflow_dispatcher = airflow_dispatcher or dispatch_airflow_dag

    async def run(
        self,
        workflow_name: str,
        local_runner: Callable[[], Awaitable[dict]],
        *,
        dispatch_payload: dict | None = None,
    ) -> dict:
        settings = self.settings_provider()
        status = self.status_provider(settings)
        engine = status.get("engine") or "local"
        local_fallback_enabled = _local_fallback_enabled(settings)
        if engine == "prefect" and status.get("ready"):
            result = await self.prefect_flow_runner(workflow_name, local_runner)
            return _attach_execution_metadata(
                result,
                requested_engine=engine,
                executed_engine="prefect",
                mode="prefect_flow",
                fallback_reason=None,
                local_fallback_enabled=local_fallback_enabled,
            )
        if engine == "temporal" and status.get("ready"):
            result = await self.temporal_dispatcher(workflow_name, dispatch_payload or {}, settings)
            return _attach_execution_metadata(
                result,
                requested_engine=engine,
                executed_engine="temporal",
                mode="temporal_workflow_dispatch",
                fallback_reason=None,
                local_fallback_enabled=local_fallback_enabled,
                external_run_id=result.get("external_run_id"),
                external_url=result.get("external_url"),
            )
        if engine == "airflow" and status.get("ready"):
            result = await self.airflow_dispatcher(workflow_name, dispatch_payload or {}, settings)
            return _attach_execution_metadata(
                result,
                requested_engine=engine,
                executed_engine="airflow",
                mode="airflow_dag_dispatch",
                fallback_reason=None,
                local_fallback_enabled=local_fallback_enabled,
                external_run_id=result.get("external_run_id"),
                external_url=result.get("external_url"),
            )
        if engine == "local":
            result = await local_runner()
            return _attach_execution_metadata(
                result,
                requested_engine=engine,
                executed_engine="local",
                mode="local_checkpoint",
                fallback_reason=None,
                local_fallback_enabled=local_fallback_enabled,
            )

        fallback_reason = status.get("fallback_reason") or f"external_dispatch_not_configured:{engine}"
        if not local_fallback_enabled:
            raise WorkflowOrchestrationError(engine=engine, reason=fallback_reason)
        result = await local_runner()
        return _attach_execution_metadata(
            result,
            requested_engine=engine,
            executed_engine="local",
            mode="local_checkpoint_fallback",
            fallback_reason=fallback_reason,
            local_fallback_enabled=local_fallback_enabled,
        )


async def run_prefect_flow(
    workflow_name: str,
    local_runner: Callable[[], Awaitable[dict]],
) -> dict:
    try:
        from prefect import flow
    except Exception as exc:  # pragma: no cover - guarded by status in normal path
        raise RuntimeError("Prefect is not available for workflow execution") from exc

    @flow(name=workflow_name)
    async def _flow() -> dict:
        return await local_runner()

    return await _flow()


async def dispatch_temporal_workflow(
    workflow_name: str,
    dispatch_payload: dict,
    settings: Any,
) -> dict:
    address = str(getattr(settings, "temporal_address", "") or "").strip()
    namespace = str(getattr(settings, "temporal_namespace", "") or "").strip()
    task_queue = str(getattr(settings, "temporal_task_queue", "") or "").strip()
    temporal_workflow_name = str(
        getattr(settings, "temporal_workflow_name", "") or "StockAnalysisPipeline"
    ).strip()
    missing = [
        name
        for name, value in {
            "temporal_address": address,
            "temporal_namespace": namespace,
            "temporal_task_queue": task_queue,
            "temporal_workflow_name": temporal_workflow_name,
        }.items()
        if not value
    ]
    if missing:
        raise WorkflowOrchestrationError(
            engine="temporal",
            reason="missing_settings:" + ",".join(missing),
        )
    try:
        from temporalio.client import Client
    except Exception as exc:
        raise WorkflowOrchestrationError(engine="temporal", reason="missing_dependency:temporalio") from exc

    timeout = max(1.0, float(getattr(settings, "temporal_timeout_seconds", 15.0) or 15.0))
    run_id = dispatch_payload.get("run_id")
    workflow_id = _temporal_workflow_id(workflow_name, run_id)
    workflow_payload = {
        "workflow_name": workflow_name,
        "payload": dispatch_payload,
    }
    try:
        client = await asyncio.wait_for(
            Client.connect(address, namespace=namespace),
            timeout=timeout,
        )
        handle = await asyncio.wait_for(
            client.start_workflow(
                temporal_workflow_name,
                workflow_payload,
                id=workflow_id,
                task_queue=task_queue,
            ),
            timeout=timeout,
        )
    except Exception as exc:
        raise WorkflowOrchestrationError(engine="temporal", reason=f"temporal_dispatch_failed:{exc}") from exc

    external_run_id = str(getattr(handle, "result_run_id", None) or getattr(handle, "id", None) or workflow_id)
    return {
        "status": "dispatched",
        "workflow_name": workflow_name,
        "run_id": run_id,
        "external_workflow_id": str(getattr(handle, "id", None) or workflow_id),
        "external_run_id": external_run_id,
        "external_url": _temporal_workflow_url(
            str(getattr(settings, "temporal_ui_url", "") or ""),
            namespace,
            str(getattr(handle, "id", None) or workflow_id),
        ),
    }


async def dispatch_airflow_dag(
    workflow_name: str,
    dispatch_payload: dict,
    settings: Any,
) -> dict:
    api_url = str(getattr(settings, "airflow_api_url", "") or "").strip()
    dag_id = str(getattr(settings, "airflow_dag_id", "") or "").strip()
    if not api_url:
        raise WorkflowOrchestrationError(engine="airflow", reason="missing_settings:airflow_api_url")
    if not dag_id:
        raise WorkflowOrchestrationError(engine="airflow", reason="missing_settings:airflow_dag_id")

    run_id = dispatch_payload.get("run_id")
    external_run_id = _airflow_dag_run_id(workflow_name, run_id)
    endpoint = _airflow_dag_runs_endpoint(api_url, dag_id)
    request_body = {
        "dag_run_id": external_run_id,
        "conf": {
            "workflow_name": workflow_name,
            "payload": dispatch_payload,
        },
    }
    timeout = max(1.0, float(getattr(settings, "airflow_timeout_seconds", 15.0) or 15.0))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                endpoint,
                json=request_body,
                headers=_airflow_headers(settings),
                auth=_airflow_auth(settings),
            )
            response.raise_for_status()
            body = _safe_json(response)
    except httpx.HTTPError as exc:
        raise WorkflowOrchestrationError(engine="airflow", reason=f"airflow_dispatch_failed:{exc}") from exc
    return {
        "status": "dispatched",
        "workflow_name": workflow_name,
        "run_id": run_id,
        "external_run_id": str(body.get("dag_run_id") or external_run_id),
        "external_url": _airflow_dag_run_url(api_url, dag_id, str(body.get("dag_run_id") or external_run_id)),
        "external_response": {
            "state": body.get("state"),
            "logical_date": body.get("logical_date"),
            "execution_date": body.get("execution_date"),
        },
    }


def _attach_execution_metadata(
    result: dict,
    *,
    requested_engine: str,
    executed_engine: str,
    mode: str,
    fallback_reason: str | None,
    local_fallback_enabled: bool,
    external_run_id: str | None = None,
    external_url: str | None = None,
) -> dict:
    metadata = {
        "requested_engine": requested_engine,
        "executed_engine": executed_engine,
        "mode": mode,
        "external_engine": executed_engine != "local",
        "fallback_reason": fallback_reason,
        "local_fallback_enabled": local_fallback_enabled,
        "external_run_id": external_run_id,
        "external_url": external_url,
    }
    return {**result, "workflow_orchestration": metadata}


def workflow_orchestration_status(
    settings: Any,
    dependency_checker: Callable[[str], bool] | None = None,
) -> dict:
    engine = str(getattr(settings, "workflow_engine", "local") or "local").strip().lower()
    dependency_checker = dependency_checker or _module_available
    base = {
        "engine": engine,
        "supported_engines": sorted(SUPPORTED_WORKFLOW_ENGINES),
        "checkpoint_store": "analysis_run.payload_json",
        "workflow_payload_version": 2,
        "local_fallback_enabled": bool(getattr(settings, "workflow_local_fallback_enabled", True)),
        "ready": False,
        "external_engine": engine != "local",
        "dependency": None,
        "dependency_available": None,
        "configuration": {},
        "fallback_reason": None,
    }
    if engine == "local":
        return {
            **base,
            "ready": True,
            "external_engine": False,
            "mode": "local_checkpoint",
            "configuration": {
                "recoverable_from_analysis_run": True,
                "run_api_resume_summary_enabled": True,
                "visual_monitoring": "analysis_run_payload",
            },
        }
    if engine == "prefect":
        dependency = "prefect"
        dependency_available = _safe_dependency_check(dependency_checker, dependency)
        api_url = str(getattr(settings, "prefect_api_url", "") or "").strip()
        return {
            **base,
            "mode": "external_orchestrator",
            "dependency": dependency,
            "dependency_available": dependency_available,
            "ready": bool(dependency_available),
            "configuration": {
                "api_url_configured": bool(api_url),
                "api_url": _redact_url(api_url),
                "can_run_local_server": True,
            },
            "fallback_reason": None if dependency_available else f"missing_dependency:{dependency}",
        }
    if engine == "temporal":
        dependency = "temporalio"
        dependency_available = _safe_dependency_check(dependency_checker, dependency)
        address = str(getattr(settings, "temporal_address", "") or "").strip()
        namespace = str(getattr(settings, "temporal_namespace", "") or "").strip()
        task_queue = str(getattr(settings, "temporal_task_queue", "") or "").strip()
        workflow_name = str(getattr(settings, "temporal_workflow_name", "") or "").strip()
        missing = [
            name
            for name, value in {
                "temporal_address": address,
                "temporal_namespace": namespace,
                "temporal_task_queue": task_queue,
                "temporal_workflow_name": workflow_name,
            }.items()
            if not value
        ]
        ready = bool(dependency_available) and not missing
        return {
            **base,
            "mode": "external_orchestrator",
            "dependency": dependency,
            "dependency_available": dependency_available,
            "ready": ready,
            "configuration": {
                "address": address,
                "namespace": namespace,
                "task_queue": task_queue,
                "workflow_name": workflow_name,
                "ui_url": _redact_url(str(getattr(settings, "temporal_ui_url", "") or "").strip()),
                "timeout_seconds": max(
                    1.0,
                    float(getattr(settings, "temporal_timeout_seconds", 15.0) or 15.0),
                ),
            },
            "fallback_reason": _workflow_fallback_reason(dependency, dependency_available, missing),
        }
    if engine == "airflow":
        dependency = "airflow_rest_api"
        dependency_available = True
        api_url = str(getattr(settings, "airflow_api_url", "") or "").strip()
        dag_id = str(getattr(settings, "airflow_dag_id", "") or "").strip()
        missing = [
            name
            for name, value in {
                "airflow_api_url": api_url,
                "airflow_dag_id": dag_id,
            }.items()
            if not value
        ]
        ready = not missing
        return {
            **base,
            "mode": "external_orchestrator",
            "dependency": dependency,
            "dependency_available": dependency_available,
            "ready": ready,
            "configuration": {
                "api_url_configured": bool(api_url),
                "api_url": _redact_url(api_url),
                "dag_id": dag_id,
                "api_token_configured": bool(getattr(settings, "airflow_api_token", None)),
                "basic_auth_configured": bool(
                    getattr(settings, "airflow_username", "")
                    and getattr(settings, "airflow_password", None)
                ),
                "timeout_seconds": max(
                    1.0,
                    float(getattr(settings, "airflow_timeout_seconds", 15.0) or 15.0),
                ),
            },
            "fallback_reason": _workflow_fallback_reason(dependency, dependency_available, missing),
        }
    return {
        **base,
        "mode": "unsupported",
        "fallback_reason": f"unsupported_engine:{engine}",
    }


def _workflow_fallback_reason(
    dependency: str,
    dependency_available: bool,
    missing_settings: list[str],
) -> str | None:
    if not dependency_available:
        return f"missing_dependency:{dependency}"
    if missing_settings:
        return "missing_settings:" + ",".join(missing_settings)
    return None


def _local_fallback_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "workflow_local_fallback_enabled", True))


def _safe_dependency_check(checker: Callable[[str], bool], dependency: str) -> bool:
    try:
        return bool(checker(dependency))
    except Exception:
        return False


def _module_available(module_name: str) -> bool:
    return find_spec(module_name) is not None


def _redact_url(url: str) -> str:
    if not url:
        return ""
    if "@" not in url:
        return url
    prefix, suffix = url.rsplit("@", 1)
    if ":" not in prefix:
        return url
    scheme_user, _password = prefix.rsplit(":", 1)
    return f"{scheme_user}:***@{suffix}"


def _airflow_dag_run_id(workflow_name: str, run_id: Any = None) -> str:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    normalized = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in workflow_name)
    if run_id is not None:
        return f"stock__{normalized}__run_{run_id}__{suffix}"
    return f"stock__{normalized}__{suffix}"


def _temporal_workflow_id(workflow_name: str, run_id: Any = None) -> str:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    normalized = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in workflow_name)
    if run_id is not None:
        return f"stock-{normalized}-run-{run_id}-{suffix}"
    return f"stock-{normalized}-{suffix}"


def _temporal_workflow_url(ui_url: str, namespace: str, workflow_id: str) -> str | None:
    if not ui_url:
        return None
    base = ui_url.rstrip("/")
    return f"{base}/namespaces/{namespace}/workflows/{workflow_id}"


def _airflow_dag_runs_endpoint(api_url: str, dag_id: str) -> str:
    base = api_url.rstrip("/") + "/"
    if base.rstrip("/").endswith("/api/v1"):
        return urljoin(base, f"dags/{dag_id}/dagRuns")
    return urljoin(base, f"api/v1/dags/{dag_id}/dagRuns")


def _airflow_dag_run_url(api_url: str, dag_id: str, dag_run_id: str) -> str:
    base = api_url.rstrip("/")
    if base.endswith("/api/v1"):
        base = base[: -len("/api/v1")]
    return f"{base}/dags/{dag_id}/grid?dag_run_id={dag_run_id}"


def _airflow_headers(settings: Any) -> dict:
    token = getattr(settings, "airflow_api_token", None)
    return {"Authorization": f"Bearer {token}"} if token else {}


def _airflow_auth(settings: Any):
    username = str(getattr(settings, "airflow_username", "") or "")
    password = getattr(settings, "airflow_password", None)
    if username and password:
        return (username, password)
    return None


def _safe_json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
