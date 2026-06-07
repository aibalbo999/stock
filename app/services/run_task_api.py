from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from app.core.time import utc_now_naive
from app.models.schemas import ReportRequest
from app.services.entity_mapping import EntityMapper
from app.services.persistence import AnalysisRunRepository
from app.services.report_followup import serialize_run
from app.services.task_failure_diagnostics import (
    DATA_OPERATION_TASKS,
    parse_payload as parse_task_payload,
    run_operation as diagnostic_run_operation,
    run_retry_kind as diagnostic_run_retry_kind,
    run_source as diagnostic_run_source,
    serialized_run_payload as diagnostic_serialized_run_payload,
    task_failure_diagnostic as diagnostic_task_failure_diagnostic,
    task_next_action as diagnostic_task_next_action,
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

    def task_summary(self, days: int = 7, limit: int = 500, stale_minutes: int | None = None) -> dict:
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
            self._run_summary_row(self.serialize_run_func(run), stale_after_minutes=stale_after, now=end)
            for run in runs
        ]
        rows = [row for row in rows if row["started_at"] >= start.isoformat()]
        totals = self._task_summary_totals(rows)
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
            "by_error_category": self._count_error_categories(rows),
            "error_category_daily": self._error_category_daily_rows(rows),
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
            raise TaskQueueUnavailableError(f"task queue unavailable while cancelling task: {exc}") from exc
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
            operation_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            retried = self.queue_data_operation(operation, operation_payload)
            return {**retried, "retried_from_task_id": task_id, "retried_from_run_id": run.id}
        if retry_kind == "report_follow_up":
            follow_up_payload = self._follow_up_retry_payload(payload)
            retried = self.queue_report_follow_up(int(payload["source_report_id"]), follow_up_payload)
            return {**retried, "retried_from_task_id": task_id, "retried_from_run_id": run.id}
        if retry_kind == "report_generation":
            request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
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

    @staticmethod
    def _celery_progress(celery_info: Any) -> dict | None:
        if isinstance(celery_info, dict) and isinstance(celery_info.get("progress"), dict):
            return celery_info["progress"]
        return None

    @staticmethod
    def _progress_payload(serialized_run: dict | None, celery_progress: dict | None = None) -> dict:
        if celery_progress:
            return celery_progress
        if not serialized_run:
            return {
                "status": "unknown",
                "progress_pct": None,
                "current_step": None,
                "resume_hint": None,
            }
        workflow_summary = serialized_run.get("workflow_summary")
        if isinstance(workflow_summary, dict):
            return {
                "status": workflow_summary.get("status"),
                "progress_pct": workflow_summary.get("progress_pct"),
                "current_step": workflow_summary.get("current_step"),
                "next_incomplete_step": workflow_summary.get("next_incomplete_step"),
                "resume_hint": workflow_summary.get("resume_hint"),
            }
        status = str(serialized_run.get("status") or "unknown")
        return {
            "status": status,
            "progress_pct": 1.0 if status == "success" else 0.0 if status == "running" else None,
            "current_step": None,
            "resume_hint": None,
        }

    @staticmethod
    def _celery_status_progress(status: str | None, *, ready: bool) -> dict:
        normalized = str(status or "PENDING").upper()
        if normalized == "SUCCESS":
            return {
                "status": "success",
                "progress_pct": 1.0,
                "current_step": "task_completed",
                "resume_hint": None,
            }
        if normalized == "FAILURE":
            return {
                "status": "failed",
                "progress_pct": None,
                "current_step": "task_failed",
                "resume_hint": "任務失敗；可查看錯誤後使用重試任務。",
            }
        if normalized == "REVOKED":
            return {
                "status": "cancelled",
                "progress_pct": None,
                "current_step": "task_cancelled",
                "resume_hint": "任務已取消。",
            }
        if normalized == "RETRY":
            return {
                "status": "retrying",
                "progress_pct": 0.0,
                "current_step": "task_retrying",
                "resume_hint": "Celery 正在重試，等待 worker 更新 run 狀態。",
            }
        if normalized == "STARTED":
            return {
                "status": "running",
                "progress_pct": 0.05,
                "current_step": "worker_started",
                "resume_hint": "Worker 已接手，等待 analysis run metadata。",
            }
        return {
            "status": "queued" if not ready else normalized.casefold(),
            "progress_pct": 0.0 if not ready else None,
            "current_step": "waiting_for_worker",
            "resume_hint": "任務已送出，等待 Celery worker 建立 analysis run。",
        }

    @classmethod
    def _run_summary_row(cls, run: dict, *, stale_after_minutes: int, now: datetime) -> dict:
        payload = cls._serialized_run_payload(run)
        started_at = str(run.get("started_at") or "")
        finished_at = str(run.get("finished_at") or "")
        started_dt = cls._parse_datetime(started_at)
        finished_dt = cls._parse_datetime(finished_at)
        status = str(run.get("status") or "unknown")
        task_id = payload.get("celery_task_id")
        persisted_failure = cls._persistent_task_failure_detail(payload)
        operation = str(persisted_failure.get("operation") or cls._run_operation(payload, run))
        retry_kind = (
            persisted_failure.get("retry_kind")
            if "retry_kind" in persisted_failure
            else cls._run_retry_kind(payload, run)
        )
        retryable = bool(
            persisted_failure.get("retryable")
            if "retryable" in persisted_failure
            else task_id and retry_kind
        )
        failure_diagnostic = cls._diagnostic_from_failure_detail(persisted_failure) or cls._task_failure_diagnostic(
            status=status,
            error=run.get("error"),
            operation=operation,
            retryable=retryable,
        )
        duration_seconds = None
        if started_dt and finished_dt:
            duration_seconds = max(0.0, (finished_dt - started_dt).total_seconds())
        running_age_seconds = None
        if status == "running" and started_dt:
            running_age_seconds = max(0.0, (now - started_dt).total_seconds())
        return {
            "id": run.get("id"),
            "source": str(run.get("source") or "unknown"),
            "operation": operation,
            "status": status,
            "report_id": run.get("report_id"),
            "task_id": payload.get("celery_task_id"),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
            "running_age_seconds": round(running_age_seconds, 3) if running_age_seconds is not None else None,
            "stale_running": bool(
                running_age_seconds is not None
                and running_age_seconds >= stale_after_minutes * 60
            ),
            "error": run.get("error"),
            "error_category": failure_diagnostic.get("category"),
            "error_severity": failure_diagnostic.get("severity"),
            "error_summary": failure_diagnostic.get("summary"),
            "next_steps": failure_diagnostic.get("next_steps") or [],
            "retryable": retryable,
            "retry_kind": retry_kind,
            "retry_endpoint": persisted_failure.get("retry_endpoint")
            or (f"POST /tasks/{task_id}/retry" if task_id and retry_kind else None),
            "status_endpoint": persisted_failure.get("status_endpoint")
            or (f"GET /tasks/{task_id}" if task_id else None),
            "run_endpoint": persisted_failure.get("run_endpoint")
            or (f"GET /runs/{run.get('id')}" if run.get("id") else None),
            "next_action": persisted_failure.get("next_action") or cls._task_next_action(
                status=status,
                task_id=task_id,
                retry_kind=retry_kind,
                error=run.get("error"),
                diagnostic=failure_diagnostic,
            ),
        }

    @staticmethod
    def _persistent_task_failure_detail(payload: dict) -> dict:
        detail = payload.get("task_failure_diagnostic") if isinstance(payload, dict) else None
        return detail if isinstance(detail, dict) else {}

    @staticmethod
    def _diagnostic_from_failure_detail(detail: dict) -> dict | None:
        if not isinstance(detail, dict) or not detail.get("error_category"):
            return None
        return {
            "category": detail.get("error_category"),
            "severity": detail.get("error_severity"),
            "summary": detail.get("error_summary"),
            "next_steps": detail.get("next_steps") if isinstance(detail.get("next_steps"), list) else [],
        }

    @staticmethod
    def _serialized_run_payload(run: dict) -> dict:
        return diagnostic_serialized_run_payload(run)

    @staticmethod
    def _run_retry_kind(payload: dict, run: dict | Any) -> str | None:
        return diagnostic_run_retry_kind(payload, run)

    @staticmethod
    def _run_source(run: dict | Any) -> str:
        return diagnostic_run_source(run)

    @staticmethod
    def _task_next_action(
        *,
        status: str,
        task_id: object,
        retry_kind: str | None,
        error: object,
        diagnostic: dict | None = None,
    ) -> str:
        return diagnostic_task_next_action(
            status=status,
            task_id=task_id,
            retry_kind=retry_kind,
            error=error,
            diagnostic=diagnostic,
        )

    @staticmethod
    def _task_failure_diagnostic(
        *,
        status: str,
        error: object,
        operation: str,
        retryable: bool,
    ) -> dict:
        return diagnostic_task_failure_diagnostic(
            status=status,
            error=error,
            operation=operation,
            retryable=retryable,
        )

    @classmethod
    def _task_status_failure_detail(
        cls,
        *,
        task_id: str,
        task_status: str,
        error: object,
        serialized_run: dict | None,
    ) -> dict:
        run_payload = cls._serialized_run_payload(serialized_run or {})
        persisted_failure = cls._persistent_task_failure_detail(run_payload)
        if persisted_failure:
            return {
                **persisted_failure,
                "status_endpoint": persisted_failure.get("status_endpoint") or f"GET /tasks/{task_id}",
                "run_endpoint": persisted_failure.get("run_endpoint")
                or (
                    f"GET /runs/{serialized_run.get('id')}"
                    if isinstance(serialized_run, dict) and serialized_run.get("id")
                    else None
                ),
            }
        retry_kind = cls._run_retry_kind(run_payload, serialized_run or {}) if serialized_run else None
        retryable = bool(task_id and retry_kind)
        run_status = str((serialized_run or {}).get("status") or task_status or "unknown")
        operation = cls._run_operation(run_payload, serialized_run or {}) if serialized_run else "task_status"
        error_text = error or (serialized_run or {}).get("error")
        diagnostic = cls._task_failure_diagnostic(
            status=run_status,
            error=error_text,
            operation=operation,
            retryable=retryable,
        )
        if not diagnostic.get("category"):
            return {}
        return {
            "operation": operation,
            "error_category": diagnostic.get("category"),
            "error_severity": diagnostic.get("severity"),
            "error_summary": diagnostic.get("summary"),
            "next_steps": diagnostic.get("next_steps") or [],
            "retryable": retryable,
            "retry_kind": retry_kind,
            "retry_endpoint": f"POST /tasks/{task_id}/retry" if retryable else None,
            "status_endpoint": f"GET /tasks/{task_id}",
            "run_endpoint": (
                f"GET /runs/{serialized_run.get('id')}"
                if isinstance(serialized_run, dict) and serialized_run.get("id")
                else None
            ),
            "next_action": cls._task_next_action(
                status=run_status,
                task_id=task_id,
                retry_kind=retry_kind,
                error=error_text,
                diagnostic=diagnostic,
            ),
        }

    @staticmethod
    def _run_operation(payload: dict, run: dict) -> str:
        return diagnostic_run_operation(payload, run)

    @staticmethod
    def _task_summary_totals(rows: list[dict]) -> dict:
        completed = [
            float(row["duration_seconds"])
            for row in rows
            if row.get("duration_seconds") is not None
        ]
        success_count = sum(1 for row in rows if row.get("status") == "success")
        failed_count = sum(1 for row in rows if row.get("status") == "failed")
        cancelled_count = sum(1 for row in rows if row.get("status") == "cancelled")
        running_count = sum(1 for row in rows if row.get("status") == "running")
        total_count = len(rows)
        return {
            "run_count": total_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "cancelled_count": cancelled_count,
            "running_count": running_count,
            "stale_running_count": sum(1 for row in rows if row.get("stale_running")),
            "success_rate": round(success_count / total_count, 4) if total_count else None,
            "avg_duration_seconds": round(sum(completed) / len(completed), 3) if completed else None,
        }

    @staticmethod
    def _count_error_categories(rows: list[dict]) -> list[dict]:
        counts: dict[tuple[str, str], int] = {}
        for row in rows:
            category = row.get("error_category")
            if not category:
                continue
            severity = str(row.get("error_severity") or "unknown")
            key = (str(category), severity)
            counts[key] = counts.get(key, 0) + 1
        return [
            {"error_category": category, "severity": severity, "count": count}
            for (category, severity), count in sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )
        ]

    @classmethod
    def _error_category_daily_rows(cls, rows: list[dict]) -> list[dict]:
        counts: dict[tuple[str, str, str], int] = {}
        for row in rows:
            category = row.get("error_category")
            if not category:
                continue
            started_at = cls._parse_datetime(row.get("started_at"))
            date_value = started_at.date().isoformat() if started_at else "unknown"
            severity = str(row.get("error_severity") or "unknown")
            key = (date_value, str(category), severity)
            counts[key] = counts.get(key, 0) + 1
        return [
            {
                "date": date_value,
                "error_category": category,
                "severity": severity,
                "count": count,
            }
            for (date_value, category, severity), count in sorted(
                counts.items(),
                key=lambda item: (item[0][0], item[0][1], item[0][2]),
            )
        ]

    @staticmethod
    def _count_rows(rows: list[dict], key: str) -> list[dict]:
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row.get(key) or "unknown")] = counts.get(str(row.get(key) or "unknown"), 0) + 1
        return [
            {key: bucket, "count": count}
            for bucket, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None
