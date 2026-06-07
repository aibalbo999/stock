from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from app.models.schemas import ReportRequest
from app.services.report_generator import ReportExecutionError


class PipelineApiService:
    def __init__(
        self,
        *,
        workflow_runner_factory: Callable[[], Any],
        standard_pipeline_factory: Callable[[], Any],
        discovered_pipeline_factory: Callable[[], Any],
        run_state_factory: Callable[[], Any] | None = None,
        topic_discovery_request_cls: type | None = None,
    ) -> None:
        self.workflow_runner_factory = workflow_runner_factory
        self.standard_pipeline_factory = standard_pipeline_factory
        self.discovered_pipeline_factory = discovered_pipeline_factory
        self.run_state_factory = run_state_factory
        self.topic_discovery_request_cls = topic_discovery_request_cls

    async def run_standard(self, request: ReportRequest) -> dict:
        return await self._run_with_orchestration(
            "standard_report_pipeline",
            lambda: self.standard_pipeline_factory().run(request),
            dispatch_payload={
                "operation": "run_standard",
                "request": request.model_dump(mode="json"),
            },
        )

    async def run_discovered(self, payload: Any, *, celery_task_id: str | None = None) -> dict:
        def local_runner():
            runner = self.discovered_pipeline_factory()
            if celery_task_id:
                return runner.run(payload, celery_task_id=celery_task_id)
            return runner.run(payload)

        return await self._run_with_orchestration(
            "ai_discovered_topic_pipeline",
            local_runner,
            dispatch_payload={
                "operation": "run_discovered",
                "request": self._payload_model_dump(payload),
            },
        )

    async def resume_standard_run(self, run_id: int) -> dict:
        return await self._run_with_orchestration(
            "standard_report_pipeline",
            lambda: self.standard_pipeline_factory().resume(run_id),
            dispatch_payload={
                "operation": "resume_standard",
                "run_id": run_id,
            },
        )

    async def resume_discovered_run(self, run_id: int) -> dict:
        return await self._run_with_orchestration(
            "ai_discovered_topic_pipeline",
            lambda: self.discovered_pipeline_factory().resume(run_id),
            dispatch_payload={
                "operation": "resume_discovered",
                "run_id": run_id,
            },
        )

    async def run_standard_local(self, request: ReportRequest) -> dict:
        result = await self.standard_pipeline_factory().run(request)
        return self._attach_local_worker_metadata(result)

    async def run_discovered_local(self, payload: Any) -> dict:
        result = await self.discovered_pipeline_factory().run(payload)
        return self._attach_local_worker_metadata(result)

    async def resume_standard_run_local(self, run_id: int) -> dict:
        result = await self.standard_pipeline_factory().resume(run_id)
        return self._attach_local_worker_metadata(result)

    async def resume_discovered_run_local(self, run_id: int) -> dict:
        result = await self.discovered_pipeline_factory().resume(run_id)
        return self._attach_local_worker_metadata(result)

    async def run_dispatch_payload_locally(self, payload: dict[str, Any]) -> dict:
        operation = str(payload.get("operation") or "")
        if operation == "run_standard":
            request = ReportRequest.model_validate(payload.get("request") or {})
            return await self.run_standard_local(request)
        if operation == "run_discovered":
            request = self._topic_discovery_request_from_payload(payload.get("request") or {})
            return await self.run_discovered_local(request)
        if operation == "resume_standard":
            return await self.resume_standard_run_local(self._dispatch_run_id(payload))
        if operation == "resume_discovered":
            return await self.resume_discovered_run_local(self._dispatch_run_id(payload))
        raise ReportExecutionError(f"unsupported workflow dispatch operation: {operation or 'missing'}")

    async def _run_with_orchestration(
        self,
        workflow_name: str,
        local_runner: Callable[[], Any],
        *,
        dispatch_payload: dict,
    ) -> dict:
        result = await self.workflow_runner_factory().run(
            workflow_name,
            local_runner,
            dispatch_payload=dispatch_payload,
        )
        self._persist_orchestration_metadata(result)
        return result

    def _persist_orchestration_metadata(self, result: dict) -> None:
        if self.run_state_factory is None:
            return
        metadata = result.get("workflow_orchestration")
        if not isinstance(metadata, dict):
            return
        try:
            run_id = int(result.get("run_id"))
        except (TypeError, ValueError):
            return
        if run_id <= 0:
            return
        self.run_state_factory().safe_merge_payload(
            run_id,
            {"workflow_orchestration": metadata},
        )

    def _attach_local_worker_metadata(self, result: dict) -> dict:
        metadata = {
            "requested_engine": "external_worker",
            "executed_engine": "local",
            "mode": "external_worker_local_execution",
            "external_engine": False,
            "fallback_reason": None,
            "local_fallback_enabled": True,
            "external_run_id": None,
            "external_url": None,
        }
        result = {**result, "workflow_orchestration": metadata}
        self._persist_orchestration_metadata(result)
        return result

    def _topic_discovery_request_from_payload(self, payload: dict[str, Any]) -> Any:
        if self.topic_discovery_request_cls is not None:
            return self.topic_discovery_request_cls.model_validate(payload)
        return SimpleNamespace(**payload)

    @staticmethod
    def _dispatch_run_id(payload: dict[str, Any]) -> int:
        try:
            run_id = int(payload.get("run_id"))
        except (TypeError, ValueError) as exc:
            raise ReportExecutionError("workflow dispatch payload requires a valid run_id") from exc
        if run_id <= 0:
            raise ReportExecutionError("workflow dispatch payload requires a valid run_id")
        return run_id

    @staticmethod
    def _payload_model_dump(payload: Any) -> dict:
        dump = getattr(payload, "model_dump", None)
        if callable(dump):
            try:
                return dump(mode="json")
            except TypeError:
                return dump()
        if isinstance(payload, dict):
            return dict(payload)
        return {
            key: value
            for key, value in vars(payload).items()
            if not key.startswith("_") and not callable(value)
        }
