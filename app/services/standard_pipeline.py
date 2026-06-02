from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.models.schemas import ReportRequest
from app.services.report_generator import ReportExecutionError
from app.services.report_followup import matching_follow_up_rerun_report_id
from app.services.workflow_checkpoint import WorkflowCheckpointRecorder


class StandardReportPipelineService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable,
        analysis_run_repository_cls: type,
        report_repository_cls: type,
        ingestion_pipeline_cls: type,
        report_build_service_factory: Callable[[], Any],
        workflow_recorder_factory: Callable[[], Any],
        auto_follow_up_func: Callable[[int], Awaitable[dict]],
        safe_update_run_success_func: Callable[[int, dict, int], bool],
        safe_mark_run_failed_func: Callable[[int, str], None],
        workflow_steps: list[str],
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.report_repository_cls = report_repository_cls
        self.ingestion_pipeline_cls = ingestion_pipeline_cls
        self.report_build_service_factory = report_build_service_factory
        self.workflow_recorder_factory = workflow_recorder_factory
        self.auto_follow_up_func = auto_follow_up_func
        self.safe_update_run_success_func = safe_update_run_success_func
        self.safe_mark_run_failed_func = safe_mark_run_failed_func
        self.workflow_steps = workflow_steps

    async def run(self, request: ReportRequest) -> dict:
        run_id = self._start_run(request)
        return await self._run_existing(run_id, request, start_from_step="pre_report_refresh")

    async def resume(self, run_id: int) -> dict:
        run, payload, workflow = self._load_resumable_standard_run(run_id)
        request = self._request_from_payload(payload)
        resume = (
            workflow.get("resume")
            if isinstance(workflow.get("resume"), dict)
            else WorkflowCheckpointRecorder.resume_state(workflow)
        )
        resume_from_step = str(resume.get("resume_from_step") or "")
        if resume_from_step not in self.workflow_steps:
            raise ReportExecutionError(f"standard_report_pipeline cannot resume from step: {resume_from_step}")
        self._mark_run_running(run_id)
        return await self._run_existing(
            run_id,
            request,
            start_from_step=resume_from_step,
            existing_payload=payload,
            existing_report_id=getattr(run, "report_id", None),
        )

    async def _run_existing(
        self,
        run_id: int,
        request: ReportRequest,
        *,
        start_from_step: str,
        existing_payload: dict | None = None,
        existing_report_id: int | None = None,
    ) -> dict:
        workflow = self.workflow_recorder_factory()
        if existing_payload is None:
            workflow.initialize(run_id, "standard_report_pipeline", self.workflow_steps)
        current_step = start_from_step
        try:
            if start_from_step == "pre_report_refresh":
                workflow.start_step(run_id, current_step)
                ingestion_summary = await self.ingestion_pipeline_cls().pre_report_refresh(request)
                workflow.complete_step(
                    run_id,
                    current_step,
                    {
                        "news_count": (ingestion_summary.get("news") or {}).get("count", 0),
                        "company_filing_count": (ingestion_summary.get("company_filings") or {}).get("stored_count", 0),
                    },
                )
                current_step = "report_build"
            else:
                ingestion_summary = self._checkpoint_ingestion_summary(existing_payload or {})

            report_result = None
            response = None
            report_id = existing_report_id
            quality_gate = (existing_payload or {}).get("quality_gate") or {}
            if start_from_step in {"pre_report_refresh", "report_build"}:
                current_step = "report_build"
                workflow.start_step(run_id, current_step)
                report_result = self.report_build_service_factory().build(
                    request,
                    source_count=(ingestion_summary.get("news") or {}).get("count", 0),
                )
                response = report_result["response"]
                quality_gate = report_result["quality_gate"]
                report_id = self._store_report(request, response)
                workflow.complete_step(
                    run_id,
                    current_step,
                    {
                        "report_id": report_id,
                        "quality_gate_status": quality_gate.get("status"),
                        "evidence_count": report_result["evidence_count"],
                    },
                )
            if report_id is None:
                report_id = self._checkpoint_report_id(existing_payload or {})
            if report_id is None:
                raise ReportExecutionError("standard_report_pipeline resume requires an existing report_id")
            if response is None:
                response = self._load_report_response(report_id)
            if report_result is None:
                report_result = self._checkpoint_report_result(existing_payload or {})
            current_step = "auto_follow_up"
            workflow.start_step(run_id, current_step)
            run_record_updated = self.safe_update_run_success_func(
                run_id,
                workflow.complete_workflow_payload(
                    run_id,
                    {
                        "request": request.model_dump(mode="json"),
                        "ingestion": ingestion_summary,
                        "quality_gate": quality_gate,
                        "report_execution": report_result["report_execution"],
                        "resumed_from_run_id": run_id if existing_payload is not None else None,
                        "resumed_from_step": start_from_step if existing_payload is not None else None,
                    },
                ),
                report_id,
            )
            auto_follow_up = await self.auto_follow_up_func(report_id)
            active_report_id = (
                matching_follow_up_rerun_report_id(
                    auto_follow_up,
                    report_id,
                    source_topic=request.topic,
                    source_tickers=request.tickers,
                )
                or report_id
            )
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "status": auto_follow_up.get("status"),
                    "rerun_report_id": active_report_id if active_report_id != report_id else None,
                },
            )
            return {
                "run_id": run_id,
                "run_record_updated": run_record_updated,
                "report_id": report_id,
                "active_report_id": active_report_id,
                "auto_follow_up": auto_follow_up,
                "ingestion": ingestion_summary,
                "quality_gate": quality_gate,
                "request": request.model_dump(mode="json"),
                "topic": request.topic,
                "report": response.model_dump(mode="json"),
                "resumed_from_step": start_from_step if existing_payload is not None else None,
            }
        except Exception as exc:
            workflow.fail_step(run_id, current_step, str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise

    def _start_run(self, request: ReportRequest) -> int:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).start(
                "pipeline_api",
                request.model_dump(mode="json"),
            )
            return run.id

    def _store_report(self, request: ReportRequest, response: Any) -> int:
        with self.session_scope_factory() as session:
            report = self.report_repository_cls(session).create(request, response)
            return report.id

    def _mark_run_running(self, run_id: int) -> None:
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            if hasattr(repository, "mark_running"):
                repository.mark_running(run_id)

    def _load_resumable_standard_run(self, run_id: int) -> tuple[Any, dict, dict]:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get(run_id)
        if run is None:
            raise ReportExecutionError(f"analysis run not found: {run_id}")
        payload = self._parse_payload(getattr(run, "payload_json", None))
        workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else None
        if not workflow or workflow.get("name") != "standard_report_pipeline":
            raise ReportExecutionError("run is not a resumable standard_report_pipeline workflow")
        resume = (
            workflow.get("resume")
            if isinstance(workflow.get("resume"), dict)
            else WorkflowCheckpointRecorder.resume_state(workflow)
        )
        if not resume.get("resumable"):
            raise ReportExecutionError("standard_report_pipeline workflow is not resumable")
        return run, payload, workflow

    @staticmethod
    def _request_from_payload(payload: dict) -> ReportRequest:
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else None
        if request_payload is None:
            request_payload = {
                key: value
                for key, value in payload.items()
                if key not in {"workflow", "ingestion", "quality_gate", "report_execution"}
            }
        return ReportRequest.model_validate(request_payload)

    @staticmethod
    def _parse_payload(payload_json: str | None) -> dict:
        if not payload_json:
            return {}
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _checkpoint_ingestion_summary(payload: dict) -> dict:
        if isinstance(payload.get("ingestion"), dict):
            return payload["ingestion"]
        workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
        pre_report_summary = StandardReportPipelineService._step_summary(workflow, "pre_report_refresh")
        return {
            "news": {"count": int(pre_report_summary.get("news_count") or 0)},
            "company_filings": {"stored_count": int(pre_report_summary.get("company_filing_count") or 0)},
            "resumed_from_checkpoint": True,
        }

    @staticmethod
    def _checkpoint_report_id(payload: dict) -> int | None:
        workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
        summary = StandardReportPipelineService._step_summary(workflow, "report_build")
        value = summary.get("report_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _checkpoint_report_result(payload: dict) -> dict:
        workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
        report_summary = StandardReportPipelineService._step_summary(workflow, "report_build")
        return {
            "report_execution": payload.get("report_execution") or {
                "evidence_count": report_summary.get("evidence_count", 0),
            },
            "evidence_count": report_summary.get("evidence_count", 0),
        }

    @staticmethod
    def _step_summary(workflow: dict, step_name: str) -> dict:
        for step in workflow.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == step_name:
                summary = step.get("summary")
                return summary if isinstance(summary, dict) else {}
        return {}

    def _load_report_response(self, report_id: int) -> Any:
        with self.session_scope_factory() as session:
            report = self.report_repository_cls(session).get(report_id)
        if report is None:
            raise ReportExecutionError(f"report not found for resume: {report_id}")
        from app.models.schemas import ReportResponse

        return ReportResponse(title=report.title, markdown=report.markdown)


__all__ = ["ReportExecutionError", "StandardReportPipelineService"]
