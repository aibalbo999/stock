from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.api.schemas import FollowUpRunRequest, TopicDiscoveryRequest
from app.core.async_bridge import run_async_from_sync
from app.core.config import get_settings
from app.core.time import today_taipei, utc_now_naive
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.company_data_audit import audit_company_data
from app.services.followup_actions import FollowUpActionPlanner, execute_follow_up_actions_sync
from app.services.ingestion import IngestionPipeline
from app.services.llm_usage import record_llm_usage_from_report_execution
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.persistence import (
    AnalysisRunRepository,
    ReportRepository,
)
from app.services.report_build import ReportBuildService
from app.services.report_followup_context import ReportFollowUpContextService
from app.services.report_files import write_report_file_with_retention
from app.services.task_cancellation import (
    TaskCancelledError,
    mark_run_cancelled,
    raise_if_task_cancelled,
)
from app.services.whitelist import SupplyChainWhitelist
from app.services.workflow_checkpoint import CELERY_REPORT_STEPS, WorkflowCheckpointRecorder
from app.tasks import after_close_report_update, report_generation
from app.tasks.celery_app import celery_app
from app.tasks.data_operations import (
    cancellable_ingestion_pipeline,
    normalize_tickers as _normalize_tickers,
    run_data_operation_payload,
)

GENERATE_REPORT_PRE_REFRESH_OPERATION = "celery.generate_report.pre_report_refresh"


def build_run_payload(
    payload: dict, task_id: str | None = None, ingestion: dict | None = None
) -> dict:
    run_payload = {"request": payload}
    if task_id:
        run_payload["celery_task_id"] = task_id
    if ingestion is not None:
        run_payload["ingestion"] = ingestion
    return run_payload


def workflow_checkpoint_recorder() -> WorkflowCheckpointRecorder:
    return WorkflowCheckpointRecorder(
        session_scope_factory=session_scope,
        analysis_run_repository_cls=AnalysisRunRepository,
    )


def _raise_if_cancelled(run_id: int) -> None:
    raise_if_task_cancelled(
        run_id,
        session_scope_factory=session_scope,
        analysis_run_repository_cls=AnalysisRunRepository,
    )


def _mark_cancelled(run_id: int) -> None:
    mark_run_cancelled(
        run_id,
        session_scope_factory=session_scope,
        analysis_run_repository_cls=AnalysisRunRepository,
    )


def _json_tickers(value: str | None) -> list[str]:
    try:
        payload = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return _normalize_tickers(payload if isinstance(payload, list) else [])


def _api_services_for_tasks():
    from app.api.runtime import get_task_api_services

    return get_task_api_services()


def _payload_datetime(payload: dict, key: str) -> datetime | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _maintenance_stale_running_before(payload: dict) -> datetime | None:
    explicit_before = _payload_datetime(payload, "stale_running_before")
    if explicit_before is not None:
        return explicit_before
    stale_minutes = int(payload.get("stale_running_minutes") or 0)
    if stale_minutes <= 0:
        return None
    return utc_now_naive() - timedelta(minutes=stale_minutes)


async def _run_discovered_report_payload(payload: dict, *, task_id: str | None = None) -> dict:
    services = _api_services_for_tasks()
    request = TopicDiscoveryRequest.model_validate(payload)
    return await services.pipeline_api().run_discovered(request, celery_task_id=task_id)


def _cancellable_ingestion_pipeline(run_id: int | None = None) -> IngestionPipeline:
    return cancellable_ingestion_pipeline(
        run_id,
        raise_if_cancelled_func=_raise_if_cancelled,
        ingestion_pipeline_cls=IngestionPipeline,
    )


async def _run_data_operation_payload(
    operation: str, payload: dict, *, run_id: int | None = None
) -> dict:
    return await run_data_operation_payload(
        operation,
        payload,
        api_services_factory=_api_services_for_tasks,
        pipeline_factory=_cancellable_ingestion_pipeline,
        raise_if_cancelled_func=_raise_if_cancelled,
        today_func=today_taipei,
        run_id=run_id,
    )


async def _run_report_follow_up_payload(payload: dict, *, task_id: str | None = None) -> dict:
    services = _api_services_for_tasks()
    request = FollowUpRunRequest.model_validate(payload.get("payload") or {})
    return await services.report_follow_up_run().run(
        int(payload["report_id"]), request, celery_task_id=task_id
    )


def _latest_report_update_target(schedule_payload: dict) -> dict:
    return after_close_report_update.latest_report_update_target(
        schedule_payload,
        session_scope_factory=session_scope,
        report_repository_cls=ReportRepository,
        analysis_run_repository_cls=AnalysisRunRepository,
        context_service_factory=ReportFollowUpContextService,
        normalize_tickers_func=_normalize_tickers,
        json_tickers_func=_json_tickers,
    )


async def _refresh_after_close_data(
    target: dict, schedule_payload: dict, *, run_id: int | None = None
) -> dict:
    return await after_close_report_update.refresh_after_close_data(
        target,
        schedule_payload,
        pipeline_factory=_cancellable_ingestion_pipeline,
        today_func=today_taipei,
        run_id=run_id,
    )


def _count_sufficient_company_filings(tickers: list[str]) -> int:
    return len(CandidateRevalidationService().sufficient_company_filing_tickers(tickers))


def _rerun_after_close_report(target: dict) -> dict:
    return after_close_report_update.rerun_after_close_report(
        target,
        report_build_service_factory=ReportBuildService,
        supply_chain_whitelist_cls=SupplyChainWhitelist,
        count_sufficient_company_filings_func=_count_sufficient_company_filings,
        create_report_with_retention_func=_create_report_with_retention,
        write_report_file_with_retention_func=_write_report_file_with_retention,
        combined_report_retention_func=_combined_report_retention,
        record_llm_usage_func=record_llm_usage_from_report_execution,
    )


def _coverage_after_close_update(target: dict) -> dict:
    return after_close_report_update.coverage_after_close_update(
        target,
        session_scope_factory=session_scope,
        market_repository_cls=MarketRepository,
        monthly_revenue_repository_cls=MonthlyRevenueRepository,
        valuation_metric_repository_cls=ValuationMetricRepository,
        financial_metric_repository_cls=FinancialMetricRepository,
        audit_company_data_func=audit_company_data,
    )


def _write_report_file(request: ReportRequest, response) -> Path:
    return _write_report_file_with_retention(request, response)["path"]


def _write_report_file_with_retention(request: ReportRequest, response) -> dict:
    settings = get_settings()
    retention = write_report_file_with_retention(Path(settings.report_dir), request, response)
    return {
        **retention,
        "path": retention["path"],
    }


def _create_report_with_retention(
    request: ReportRequest,
    response,
) -> tuple[int, dict]:
    with session_scope() as session:
        repository = ReportRepository(session)
        report = repository.create(request, response)
        report_id = report.id
        retention = getattr(repository, "last_retention_result", {}) or {}
    return report_id, retention


def _combined_report_retention(db_retention: dict | None, file_retention: dict | None) -> dict:
    return after_close_report_update.combined_report_retention(db_retention, file_retention)


def _run_generate_report_payload(payload: dict, *, task_id: str | None = None) -> dict:
    return report_generation.run_generate_report_payload(
        payload,
        task_id=task_id,
        session_scope_factory=session_scope,
        analysis_run_repository_cls=AnalysisRunRepository,
        report_request_cls=ReportRequest,
        build_run_payload_func=build_run_payload,
        workflow_factory=workflow_checkpoint_recorder,
        workflow_steps=CELERY_REPORT_STEPS,
        raise_if_cancelled_func=_raise_if_cancelled,
        mark_cancelled_func=_mark_cancelled,
        pipeline_factory=_cancellable_ingestion_pipeline,
        run_async_func=run_async_from_sync,
        pre_report_refresh_operation=GENERATE_REPORT_PRE_REFRESH_OPERATION,
        report_build_service_factory=ReportBuildService,
        follow_up_action_planner_factory=FollowUpActionPlanner,
        execute_follow_up_actions_func=execute_follow_up_actions_sync,
        create_report_with_retention_func=_create_report_with_retention,
        record_llm_usage_func=record_llm_usage_from_report_execution,
        write_report_file_with_retention_func=_write_report_file_with_retention,
        combined_report_retention_func=_combined_report_retention,
    )


@celery_app.task(bind=True, name="app.tasks.tasks.discovered_report_task")
def discovered_report_task(self, payload: dict) -> dict:
    init_db()
    task_id = getattr(self.request, "id", None)
    result = run_async_from_sync(
        _run_discovered_report_payload(payload, task_id=task_id),
        operation="celery.discovered_report",
    )
    return {
        **result,
        "task_id": task_id,
    }


@celery_app.task(bind=True, name="app.tasks.tasks.data_operation_task")
def data_operation_task(self, payload: dict) -> dict:
    init_db()
    task_id = getattr(self.request, "id", None)
    operation = str(payload.get("operation") or "")
    operation_payload = payload.get("payload") or {}
    with session_scope() as session:
        run = AnalysisRunRepository(session).start(
            "celery_data_operation",
            {
                "task": "data_operation",
                "operation": operation,
                "payload": operation_payload,
                "celery_task_id": task_id,
            },
        )
        run_id = run.id
    try:
        _raise_if_cancelled(run_id)
        result = run_async_from_sync(
            _run_data_operation_payload(operation, operation_payload, run_id=run_id),
            operation=f"celery.data_operation.{operation or 'unknown'}",
        )
        _raise_if_cancelled(run_id)
        with session_scope() as session:
            repository = AnalysisRunRepository(session)
            repository.update_payload(
                run_id,
                {
                    "task": "data_operation",
                    "operation": operation,
                    "payload": operation_payload,
                    "celery_task_id": task_id,
                    "result": result,
                },
            )
            repository.mark_success(run_id, report_id=None)
        return {
            "task_id": task_id,
            "run_id": run_id,
            "operation": operation,
            "result": result,
        }
    except TaskCancelledError:
        _mark_cancelled(run_id)
        return {
            "task_id": task_id,
            "run_id": run_id,
            "operation": operation,
            "cancelled": True,
        }
    except Exception as exc:
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise


@celery_app.task(bind=True, name="app.tasks.tasks.maintenance_cleanup_task")
def maintenance_cleanup_task(self, payload: dict | None = None) -> dict:
    init_db()
    task_id = getattr(self.request, "id", None)
    cleanup_payload = payload or {}
    with session_scope() as session:
        run = AnalysisRunRepository(session).start(
            "celery_maintenance_cleanup",
            {
                "task": "maintenance_cleanup",
                "payload": cleanup_payload,
                "celery_task_id": task_id,
            },
        )
        run_id = run.id
    try:
        result = (
            _api_services_for_tasks()
            .data_operations_api()
            .maintenance_cleanup(
                failed_runs=bool(cleanup_payload.get("failed_runs", False)),
                orphan_report_refs=bool(cleanup_payload.get("orphan_report_refs", True)),
                latest_reports_only=bool(cleanup_payload.get("latest_reports_only", True)),
                stale_running_before=_maintenance_stale_running_before(cleanup_payload),
                runs_before=_payload_datetime(cleanup_payload, "runs_before"),
                reports_before=_payload_datetime(cleanup_payload, "reports_before"),
            )
        )
        with session_scope() as session:
            repository = AnalysisRunRepository(session)
            repository.update_payload(
                run_id,
                {
                    "task": "maintenance_cleanup",
                    "payload": cleanup_payload,
                    "celery_task_id": task_id,
                    "result": result,
                },
            )
            repository.mark_success(run_id, report_id=None)
        return {
            "task_id": task_id,
            "run_id": run_id,
            "result": result,
        }
    except Exception as exc:
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise


@celery_app.task(bind=True, name="app.tasks.tasks.report_follow_up_task")
def report_follow_up_task(self, payload: dict) -> dict:
    init_db()
    task_id = getattr(self.request, "id", None)
    result = run_async_from_sync(
        _run_report_follow_up_payload(payload, task_id=task_id),
        operation="celery.report_follow_up",
    )
    return {
        **result,
        "task_id": task_id,
    }


@celery_app.task(bind=True, name="app.tasks.tasks.generate_report_task")
def generate_report_task(self, payload: dict) -> dict:
    init_db()
    task_id = getattr(self.request, "id", None)
    return _run_generate_report_payload(payload, task_id=task_id)


@celery_app.task(bind=True, name="app.tasks.tasks.after_close_report_update_task")
def after_close_report_update_task(self, payload: dict | None = None) -> dict:
    init_db()
    schedule_payload = payload or {}
    task_id = getattr(self.request, "id", None)
    with session_scope() as session:
        run = AnalysisRunRepository(session).start(
            "celery_after_close",
            {
                "task": "after_close_report_update",
                "schedule": schedule_payload,
                "celery_task_id": task_id,
            },
        )
        run_id = run.id
    try:
        _raise_if_cancelled(run_id)
        target = _latest_report_update_target(schedule_payload)
        _raise_if_cancelled(run_id)
        refresh = run_async_from_sync(
            _refresh_after_close_data(target, schedule_payload, run_id=run_id),
            operation="celery.after_close.refresh_data",
        )
        _raise_if_cancelled(run_id)
        coverage = _coverage_after_close_update(target)
        _raise_if_cancelled(run_id)
        rerun_report = None
        if bool(schedule_payload.get("rerun_report", True)):
            rerun_report = _rerun_after_close_report(target)
            _raise_if_cancelled(run_id)
        final_report_id = (rerun_report or {}).get("report_id") or target["report_id"]
        output_path = (rerun_report or {}).get("path")
        result = {
            "task_id": task_id,
            "run_id": run_id,
            "source_report_id": target["report_id"],
            "report_id": final_report_id,
            "topic": target["topic"],
            "tickers": target["tickers"],
            "refresh": refresh,
            "coverage": coverage,
            "rerun_report": rerun_report,
        }
        with session_scope() as session:
            repository = AnalysisRunRepository(session)
            repository.update_payload(
                run_id,
                {
                    "task": "after_close_report_update",
                    "schedule": schedule_payload,
                    "celery_task_id": task_id,
                    "source_report_id": target["report_id"],
                    "source_report_topic": target["topic"],
                    "source_report_generated_at": target["generated_at"],
                    "request": target["request"].model_dump(mode="json"),
                    "refresh": refresh,
                    "coverage": coverage,
                    "rerun_report": rerun_report,
                },
            )
            repository.mark_success(run_id, final_report_id, output_path)
        return result
    except TaskCancelledError:
        _mark_cancelled(run_id)
        return {
            "task_id": task_id,
            "run_id": run_id,
            "cancelled": True,
        }
    except Exception as exc:
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise
