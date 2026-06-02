from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from app.models.schemas import ReportRequest
from app.services.entity_mapping import EntityMapper
from app.services.persistence import AnalysisRunRepository
from app.services.report_followup import serialize_run


class RunTaskApiError(ValueError):
    pass


class RunTaskNotFound(RunTaskApiError):
    pass


class AsyncReportValidationError(RunTaskApiError):
    pass


class RunTaskApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
        entity_mapper_cls: type[EntityMapper] = EntityMapper,
        report_task: Any = None,
        celery_app: Any = None,
        serialize_run_func: Callable[[Any], dict] = serialize_run,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.entity_mapper_cls = entity_mapper_cls
        self.report_task = report_task
        self.celery_app = celery_app
        self.serialize_run_func = serialize_run_func

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self.session_scope_factory() as session:
            runs = self.analysis_run_repository_cls(session).latest(limit)
        return [self.serialize_run_func(run) for run in runs]

    def get_run(self, run_id: int) -> dict:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get(run_id)
        if run is None:
            raise RunTaskNotFound("run not found")
        return self.serialize_run_func(run)

    def delete_run(self, run_id: int) -> dict:
        with self.session_scope_factory() as session:
            deleted = self.analysis_run_repository_cls(session).delete(run_id)
        if not deleted:
            raise RunTaskNotFound("run not found")
        return {"deleted": True, "id": run_id}

    def generate_report_async(self, request: ReportRequest) -> dict:
        mapper = self.entity_mapper_cls()
        filtered_tickers = mapper.filter_allowed_tickers(request.tickers)
        dropped_tickers = [ticker for ticker in request.tickers if ticker not in set(filtered_tickers)]
        if dropped_tickers:
            raise AsyncReportValidationError(
                "async report generation received tickers outside the static whitelist: "
                + ", ".join(dropped_tickers)
            )
        if not filtered_tickers:
            raise AsyncReportValidationError("async report generation requires at least one whitelisted ticker")
        if self.report_task is None:
            raise RuntimeError("async report task is not configured")
        task = self.report_task.delay(request.model_dump(mode="json"))
        return {"task_id": task.id, "status": "queued"}

    def get_task_status(self, task_id: str) -> dict:
        if self.celery_app is None:
            raise RuntimeError("celery app is not configured")
        result = self.celery_app.AsyncResult(task_id)
        response = {
            "task_id": task_id,
            "status": result.status,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else False,
        }
        if result.ready():
            if result.successful():
                response["result"] = result.result
            else:
                response["error"] = str(result.result)
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get_by_celery_task_id(task_id)
        if run is not None:
            response["run"] = self.serialize_run_func(run)
        return response

    def get_run_by_task_id(self, task_id: str) -> dict:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get_by_celery_task_id(task_id)
        if run is None:
            raise RunTaskNotFound("run not found for task")
        return self.serialize_run_func(run)
