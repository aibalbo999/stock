from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Any

from app.core.time import utc_now_naive
from app.models.schemas import ReportRequest
from app.services.entity_mapping import EntityMapper
from app.services.persistence import AnalysisRunRepository
from app.services.report_followup import serialize_run
from app.services.run_task_api_summary import (
    alert_severity_for_category as _alert_severity_for_category,
    alert_sort_key as _alert_sort_key,
    celery_progress as _celery_progress,
    celery_status_progress as _celery_status_progress,
    count_error_categories as _count_error_categories,
    count_rows as _count_rows,
    diagnostic_from_failure_detail as _diagnostic_from_failure_detail,
    error_category_daily_rows as _error_category_daily_rows,
    parse_datetime as _parse_datetime,
    persistent_task_failure_detail as _persistent_task_failure_detail,
    progress_payload as _progress_payload,
    run_operation as _run_operation,
    run_retry_kind as _run_retry_kind,
    run_source as _run_source,
    run_summary_row as _run_summary_row,
    serialized_run_payload as _serialized_run_payload,
    task_failure_alert_message as _task_failure_alert_message,
    task_failure_alerts as _task_failure_alerts,
    task_failure_diagnostic as _task_failure_diagnostic,
    task_next_action as _task_next_action,
    task_status_failure_detail as _task_status_failure_detail,
    task_summary_totals as _task_summary_totals,
)
from app.services.task_failure_diagnostics import (
    DATA_OPERATION_TASKS,
    parse_payload as parse_task_payload,
)


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
        settings_provider: Callable[[], Any] | None = None,
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
        self.settings_provider = settings_provider

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self.session_scope_factory() as session:
            runs = self.analysis_run_repository_cls(session).latest(limit)
        return [self.serialize_run_func(run) for run in runs]

    def task_summary(
        self, days: int = 7, limit: int = 500, stale_minutes: int | None = None
    ) -> dict:
        safe_days = max(1, min(int(days or 7), 90))
        safe_limit = max(1, min(int(limit or 500), 1000))
        if stale_minutes is None and self.settings_provider is not None:
            settings = self.settings_provider()
            stale_minutes = int(getattr(settings, "task_observability_stale_minutes", 60) or 60)
        stale_after = max(5, int(stale_minutes or 60))
        end = utc_now_naive()
        start = end - timedelta(days=safe_days)
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            since = getattr(repository, "since", None)
            runs = since(start, safe_limit) if callable(since) else repository.latest(safe_limit)
        rows = [
            self._run_summary_row(
                self.serialize_run_func(run), stale_after_minutes=stale_after, now=end
            )
            for run in runs
        ]
        rows = [row for row in rows if row["started_at"] >= start.isoformat()]
        totals = self._task_summary_totals(rows)
        by_error_category = self._count_error_categories(rows)
        error_category_daily = self._error_category_daily_rows(rows)
        return {
            "window": {
                "days": safe_days,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "stale_minutes": stale_after,
            },
            "totals": totals,
            "by_status": self._count_rows(rows, "status"),
            "by_source": self._count_rows(rows, "source"),
            "by_operation": self._count_rows(rows, "operation"),
            "by_error_category": by_error_category,
            "error_category_daily": error_category_daily,
            "alerts": self._task_failure_alerts(rows, error_category_daily),
            "recent_failures": [
                row for row in rows if row["status"] in {"failed", "cancelled"} or row.get("error")
            ][:10],
            "stale_running": [row for row in rows if row.get("stale_running")][:10],
            "recent": rows[:20],
        }

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
        dropped_tickers = [
            ticker for ticker in request.tickers if ticker not in set(filtered_tickers)
        ]
        if dropped_tickers:
            raise AsyncReportValidationError(
                "async report generation received tickers outside the static whitelist: "
                + ", ".join(dropped_tickers)
            )
        if not filtered_tickers:
            raise AsyncReportValidationError(
                "async report generation requires at least one whitelisted ticker"
            )
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
            raise AsyncReportValidationError(
                f"unsupported data operation task: {operation or 'missing'}"
            )
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
            raise TaskQueueUnavailableError(
                f"task queue unavailable while checking task status: {exc}"
            ) from exc
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
        serialized_run = self.serialize_run_func(run) if run is not None else None
        celery_progress = self._celery_progress(getattr(result, "info", None))
        if serialized_run is not None:
            response["run"] = serialized_run
            response["progress"] = self._progress_payload(serialized_run, celery_progress)
        elif celery_progress:
            response["progress"] = celery_progress
        else:
            response["progress"] = self._celery_status_progress(result.status, ready=result.ready())
        failure_detail = self._task_status_failure_detail(
            task_id=task_id,
            task_status=str(result.status or ""),
            error=response.get("error"),
            serialized_run=serialized_run,
        )
        if failure_detail:
            response.update(failure_detail)
        return response

    def get_run_by_task_id(self, task_id: str) -> dict:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get_by_celery_task_id(task_id)
        if run is None:
            raise RunTaskNotFound("run not found for task")
        return self.serialize_run_func(run)

    def cancel_task(self, task_id: str) -> dict:
        if self.celery_app is None:
            raise TaskQueueUnavailableError("task queue is not configured")
        try:
            self.celery_app.control.revoke(task_id, terminate=False)
        except Exception as exc:
            raise TaskQueueUnavailableError(
                f"task queue unavailable while cancelling task: {exc}"
            ) from exc
        run_payload = None
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            run = repository.get_by_celery_task_id(task_id)
            if run is not None:
                run_payload = self._parse_payload(getattr(run, "payload_json", None))
                run_payload["cancel_requested"] = True
                run_payload["cancel_requested_at"] = "queued_by_api"
                repository.update_payload(run.id, run_payload)
                run = repository.get(run.id)
        return {
            "task_id": task_id,
            "cancel_requested": True,
            "run": self.serialize_run_func(run) if run is not None else None,
        }

    def retry_task(self, task_id: str) -> dict:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get_by_celery_task_id(task_id)
        if run is None:
            raise RunTaskNotFound("run not found for task")
        payload = self._parse_payload(getattr(run, "payload_json", None))
        retry_kind = self._run_retry_kind(payload, run)
        if retry_kind == "data_operation":
            operation = str(payload.get("operation") or "")
            operation_payload = (
                payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            )
            retried = self.queue_data_operation(operation, operation_payload)
            return {**retried, "retried_from_task_id": task_id, "retried_from_run_id": run.id}
        if retry_kind == "report_follow_up":
            follow_up_payload = self._follow_up_retry_payload(payload)
            retried = self.queue_report_follow_up(
                int(payload["source_report_id"]), follow_up_payload
            )
            return {**retried, "retried_from_task_id": task_id, "retried_from_run_id": run.id}
        if retry_kind == "report_generation":
            request_payload = (
                payload.get("request") if isinstance(payload.get("request"), dict) else payload
            )
            retried = self.generate_report_async(ReportRequest.model_validate(request_payload))
            return {**retried, "retried_from_task_id": task_id, "retried_from_run_id": run.id}
        raise AsyncReportValidationError("task payload is not retryable")

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
    def _follow_up_retry_payload(payload: dict[str, Any]) -> dict[str, Any]:
        retry_payload = {
            key: payload.get(key)
            for key in ("purpose", "force_refresh", "record_noop", "news_limit")
            if key in payload
        }
        if "rerun_report_requested" in payload:
            retry_payload["rerun_report"] = bool(payload.get("rerun_report_requested"))
        elif isinstance(payload.get("rerun_report"), bool):
            retry_payload["rerun_report"] = payload["rerun_report"]
        elif isinstance(payload.get("rerun_report"), dict):
            retry_payload["rerun_report"] = True
        elif "rerun_report" in payload:
            retry_payload["rerun_report"] = False
        return retry_payload

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

    @staticmethod
    def _parse_payload(payload_json: str | None) -> dict:
        return parse_task_payload(payload_json)

    _alert_sort_key = staticmethod(_alert_sort_key)
    _celery_progress = staticmethod(_celery_progress)
    _progress_payload = staticmethod(_progress_payload)
    _celery_status_progress = staticmethod(_celery_status_progress)
    _run_summary_row = staticmethod(_run_summary_row)
    _persistent_task_failure_detail = staticmethod(_persistent_task_failure_detail)
    _diagnostic_from_failure_detail = staticmethod(_diagnostic_from_failure_detail)
    _serialized_run_payload = staticmethod(_serialized_run_payload)
    _run_retry_kind = staticmethod(_run_retry_kind)
    _run_source = staticmethod(_run_source)
    _task_next_action = staticmethod(_task_next_action)
    _task_failure_diagnostic = staticmethod(_task_failure_diagnostic)
    _task_status_failure_detail = staticmethod(_task_status_failure_detail)
    _run_operation = staticmethod(_run_operation)
    _task_summary_totals = staticmethod(_task_summary_totals)
    _count_error_categories = staticmethod(_count_error_categories)
    _error_category_daily_rows = staticmethod(_error_category_daily_rows)
    _task_failure_alerts = staticmethod(_task_failure_alerts)
    _alert_severity_for_category = staticmethod(_alert_severity_for_category)
    _task_failure_alert_message = staticmethod(_task_failure_alert_message)
    _count_rows = staticmethod(_count_rows)
    _parse_datetime = staticmethod(_parse_datetime)
