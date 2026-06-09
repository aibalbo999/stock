from __future__ import annotations

from typing import Any

from app.models.schemas import ReportResponse
from app.services.report_generator import ReportExecutionError
from app.services.task_cancellation import raise_if_task_cancelled
from app.services.workflow_checkpoint import WorkflowCheckpointRecorder


class DiscoveredPipelineRunStateMixin:
    def _start_run(self, payload: Any) -> int:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).start(
                "pipeline_ai_discovery",
                payload.model_dump(mode="json"),
            )
            return run.id

    def _checkpoint_stage_payload(self, run_id: int, workflow: Any, updates: dict) -> bool:
        current_payload = self._current_run_payload(run_id)
        payload = {**current_payload, **self._json_safe(updates)}
        return self._update_run_payload(
            run_id,
            workflow.payload_with_current_workflow(run_id, payload),
        )

    def _checkpoint_report_build_payload(
        self, run_id: int, workflow: Any, run_payload: dict
    ) -> bool:
        payload = workflow.payload_with_current_workflow(run_id, run_payload)
        return self._update_run_payload(run_id, payload)

    def _attach_celery_task_id(self, run_id: int, celery_task_id: str) -> bool:
        current_payload = self._current_run_payload(run_id)
        return self._update_run_payload(
            run_id, {**current_payload, "celery_task_id": celery_task_id}
        )

    def _update_run_payload(self, run_id: int, payload: dict) -> bool:
        try:
            with self.session_scope_factory() as session:
                repository = self.analysis_run_repository_cls(session)
                if not hasattr(repository, "update_payload") or repository.get(run_id) is None:
                    return False
                repository.update_payload(run_id, payload)
                return True
        except Exception:
            return False

    def _current_run_payload(self, run_id: int) -> dict:
        try:
            with self.session_scope_factory() as session:
                run = self.analysis_run_repository_cls(session).get(run_id)
            return (
                self._parse_payload(getattr(run, "payload_json", None)) if run is not None else {}
            )
        except Exception:
            return {}

    def _mark_run_running(self, run_id: int) -> None:
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            if hasattr(repository, "mark_running"):
                repository.mark_running(run_id)

    def _mark_run_cancelled(self, run_id: int, reason: str) -> None:
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            mark_cancelled = getattr(repository, "mark_cancelled", None)
            if callable(mark_cancelled):
                mark_cancelled(run_id, reason)
            else:
                self.safe_mark_run_failed_func(run_id, reason)

    def _check_cancelled(self, run_id: int) -> None:
        if self.task_cancellation_checker is not None:
            self.task_cancellation_checker(run_id)
            return
        raise_if_task_cancelled(
            run_id,
            session_scope_factory=self.session_scope_factory,
            analysis_run_repository_cls=self.analysis_run_repository_cls,
        )

    def _discovered_market_data_service(self, run_id: int) -> Any:
        try:
            return self.discovered_market_data_service_factory(
                cancellation_checker=lambda: self._check_cancelled(run_id)
            )
        except TypeError:
            service = self.discovered_market_data_service_factory()
            if hasattr(service, "cancellation_checker"):
                service.cancellation_checker = lambda: self._check_cancelled(run_id)
            return service

    def _load_resumable_discovered_run(self, run_id: int) -> tuple[Any, dict, dict]:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get(run_id)
        if run is None:
            raise ReportExecutionError(f"analysis run not found: {run_id}")
        payload = self._parse_payload(getattr(run, "payload_json", None))
        workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else None
        if not workflow or workflow.get("name") != "ai_discovered_topic_pipeline":
            raise ReportExecutionError(
                "run is not a resumable ai_discovered_topic_pipeline workflow"
            )
        resume = (
            workflow.get("resume")
            if isinstance(workflow.get("resume"), dict)
            else WorkflowCheckpointRecorder.resume_state(workflow)
        )
        if not resume.get("resumable"):
            raise ReportExecutionError("ai_discovered_topic_pipeline workflow is not resumable")
        return run, payload, workflow

    def _load_report_response(self, report_id: int) -> ReportResponse:
        with self.session_scope_factory() as session:
            report = self.report_repository_cls(session).get(report_id)
        if report is None:
            raise ReportExecutionError(f"report not found for resume: {report_id}")
        return ReportResponse(title=report.title, markdown=report.markdown)


__all__ = ["DiscoveredPipelineRunStateMixin"]
