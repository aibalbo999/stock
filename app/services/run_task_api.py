from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from app.models.schemas import ReportRequest
from app.services.entity_mapping import EntityMapper
from app.services.persistence import AnalysisRunRepository
from app.services.report_followup import serialize_run

DATA_OPERATION_TASKS = {
    "market_refresh",
    "fundamentals_refresh",
    "valuation_refresh",
    "company_filings_fetch",
    "company_filing_from_url",
    "feed_fetch",
}


class RunTaskApiError(ValueError):
    pass


class RunTaskNotFound(RunTaskApiError):
    pass


class AsyncReportValidationError(RunTaskApiError):
    pass


class TaskQueueUnavailableError(RunTaskApiError):
    pass


class RunTaskApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
        entity_mapper_cls: type[EntityMapper] = EntityMapper,
        report_task: Any = None,
        discovered_report_task: Any = None,
        data_operation_task: Any = None,
        report_follow_up_task: Any = None,
        celery_app: Any = None,
        serialize_run_func: Callable[[Any], dict] = serialize_run,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.entity_mapper_cls = entity_mapper_cls
        self.report_task = report_task
        self.discovered_report_task = discovered_report_task
        self.data_operation_task = data_operation_task
        self.report_follow_up_task = report_follow_up_task
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
        task = self._delay_task(
            self.report_task,
            request.model_dump(mode="json"),
            "async report generation",
        )
        return {"task_id": task.id, "status": "queued"}

    def generate_discovered_report_async(self, payload: Any) -> dict:
        task = self._delay_task(
            self.discovered_report_task,
            self._payload_model_dump(payload),
            "discovered report generation",
        )
        return {
            "task_id": task.id,
            "status": "queued",
            "operation": "run_discovered",
        }

    def queue_data_operation(self, operation: str, payload: dict[str, Any] | None = None) -> dict:
        if operation not in DATA_OPERATION_TASKS:
            raise AsyncReportValidationError(f"unsupported data operation task: {operation or 'missing'}")
        task = self._delay_task(
            self.data_operation_task,
            {"operation": operation, "payload": payload or {}},
            f"data operation {operation}",
        )
        return {
            "task_id": task.id,
            "status": "queued",
            "operation": operation,
        }

    def queue_report_follow_up(self, report_id: int, payload: dict[str, Any] | None = None) -> dict:
        task = self._delay_task(
            self.report_follow_up_task,
            {
                "report_id": report_id,
                "payload": payload or {},
            },
            "report follow-up",
        )
        return {
            "task_id": task.id,
            "status": "queued",
            "operation": "report_follow_up",
            "report_id": report_id,
        }

    def get_task_status(self, task_id: str) -> dict:
        if self.celery_app is None:
            raise TaskQueueUnavailableError("task queue is not configured")
        try:
            result = self.celery_app.AsyncResult(task_id)
        except Exception as exc:
            raise TaskQueueUnavailableError(f"task queue unavailable while checking task status: {exc}") from exc
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

    @staticmethod
    def _payload_model_dump(payload: Any) -> dict:
        dump = getattr(payload, "model_dump", None)
        if callable(dump):
            try:
                return dump(mode="json")
            except TypeError:
                return dump()
        return dict(payload or {})

    @staticmethod
    def _delay_task(task: Any, payload: dict[str, Any], operation: str) -> Any:
        if task is None:
            raise TaskQueueUnavailableError(f"{operation} task is not configured")
        try:
            return task.delay(payload)
        except Exception as exc:
            raise TaskQueueUnavailableError(
                f"task queue unavailable while submitting {operation}: {exc}"
            ) from exc
