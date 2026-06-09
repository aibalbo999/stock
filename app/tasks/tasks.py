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
from app.services.report_followup import (
    candidate_audit_from_run_payload,
    parse_run_payload,
    plan_quality_from_quality_gate,
    summarize_candidate_support_payload,
)
from app.services.report_followup_context import ReportFollowUpContextService
from app.services.report_files import write_report_file_with_retention
from app.services.task_cancellation import (
    TaskCancelledError,
    mark_run_cancelled,
    raise_if_task_cancelled,
)
from app.services.whitelist import SupplyChainWhitelist
from app.services.workflow_checkpoint import CELERY_REPORT_STEPS, WorkflowCheckpointRecorder
from app.tasks.celery_app import celery_app
from app.tasks.data_operations import (
    cancellable_ingestion_pipeline,
    normalize_tickers as _normalize_tickers,
    run_data_operation_payload,
)


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
    with session_scope() as session:
        reports = ReportRepository(session).latest(1)
        if not reports:
            raise RuntimeError("after-close update requires at least one generated report")
        report = reports[0]
        run = AnalysisRunRepository(session).get_by_report_id(report.id)
        run_payload = parse_run_payload(run.payload_json if run is not None else None)
        report_tickers = _json_tickers(report.tickers_json)
    context = ReportFollowUpContextService().load(report.id)
    request = context["request"]
    candidate_tickers = _normalize_tickers(
        item.get("ticker")
        for item in (
            context.get("candidate_whitelist") or candidate_audit_from_run_payload(run_payload)
        )
        if isinstance(item, dict)
    )
    configured_tickers = _normalize_tickers(schedule_payload.get("tickers") or [])
    tickers = configured_tickers or _normalize_tickers(
        [
            *report_tickers,
            *getattr(request, "tickers", []),
            *candidate_tickers,
        ]
    )
    if not tickers:
        raise RuntimeError(f"after-close update could not resolve tickers for report {report.id}")
    lookback_days = int(
        schedule_payload.get("lookback_days") or getattr(request, "lookback_days", None) or 120
    )
    return {
        "report_id": report.id,
        "topic": report.topic,
        "generated_at": report.generated_at.isoformat(),
        "run_payload": run_payload,
        "context": context,
        "request": request.model_copy(update={"tickers": tickers, "lookback_days": lookback_days}),
        "tickers": tickers,
    }


async def _refresh_after_close_data(
    target: dict, schedule_payload: dict, *, run_id: int | None = None
) -> dict:
    today = today_taipei()
    request = target["request"]
    tickers = target["tickers"]
    lookback_days = max(int(getattr(request, "lookback_days", 120) or 120), 120)
    pipeline = _cancellable_ingestion_pipeline(run_id)
    market = await pipeline.refresh_market(
        tickers,
        today - timedelta(days=lookback_days),
        today,
        filter_allowed=False,
    )
    monthly_revenue = await pipeline.refresh_monthly_revenue(
        tickers,
        today - timedelta(days=450),
        today,
        filter_allowed=False,
    )
    financial_metrics = await pipeline.refresh_financial_metrics(
        tickers,
        today - timedelta(days=365 * 6),
        today,
        filter_allowed=False,
    )
    valuations = await pipeline.refresh_valuations(
        tickers,
        today - timedelta(days=max(lookback_days, 30)),
        today,
        filter_allowed=False,
    )
    company_filings = {"status": "skipped", "reason": "refresh_company_filings=false"}
    if bool(schedule_payload.get("refresh_company_filings", True)):
        company_filings = await pipeline.ingest_company_filings(
            tickers,
            limit_per_query=2,
            filter_allowed=False,
        )
    return {
        "market": market,
        "monthly_revenue": monthly_revenue,
        "financial_metrics": financial_metrics,
        "valuations": valuations,
        "company_filings": company_filings,
    }


def _count_sufficient_company_filings(tickers: list[str]) -> int:
    return len(CandidateRevalidationService().sufficient_company_filing_tickers(tickers))


def _rerun_after_close_report(target: dict) -> dict:
    request = target["request"]
    context = target["context"]
    candidates = context.get("candidate_whitelist") or []
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(candidates) if candidates else None
    run_payload = context.get("run_payload") or target.get("run_payload") or {}
    report_result = ReportBuildService().build(
        request,
        whitelist=whitelist,
        company_filing_sufficient_count=_count_sufficient_company_filings(request.tickers),
        candidate_support=summarize_candidate_support_payload(candidates),
        plan_quality=(
            run_payload.get("plan_quality")
            or (run_payload.get("discovery") or {}).get("plan_quality")
            or plan_quality_from_quality_gate(context.get("quality_gate") or {})
        ),
    )
    response = report_result["response"]
    report_id, db_retention = _create_report_with_retention(request, response)
    record_llm_usage_from_report_execution(
        report_result.get("report_execution"),
        operation="after_close_report_rerun",
        report_id=report_id,
    )
    file_retention = _write_report_file_with_retention(request, response)
    path = file_retention["path"]
    retention = _combined_report_retention(db_retention, file_retention)
    return {
        "status": "generated",
        "report_id": report_id,
        "path": str(path),
        "retention": retention,
        "quality_gate": report_result["quality_gate"],
        "report_execution": report_result["report_execution"],
        "evidence_count": report_result["evidence_count"],
    }


def _coverage_after_close_update(target: dict) -> dict:
    tickers = target["tickers"]
    with session_scope() as session:
        market = MarketRepository(session).latest_by_tickers(tickers)
        monthly = MonthlyRevenueRepository(session).latest_by_tickers(tickers)
        valuations = ValuationMetricRepository(session).latest_by_tickers(tickers)
        financials = FinancialMetricRepository(session).by_tickers(tickers)
        audit = audit_company_data(
            session,
            tickers,
            markdown=target["context"].get("markdown") or "",
            run_payload=target.get("run_payload") or {},
        )
    financial_latest: dict[str, str] = {}
    for metric in financials:
        current = financial_latest.get(metric.ticker)
        report_date = metric.report_date.isoformat()
        if current is None or report_date > current:
            financial_latest[metric.ticker] = report_date
    return {
        "latest_dates": {
            "market": {item.ticker: item.trade_date.isoformat() for item in market},
            "monthly_revenue": {item.ticker: item.revenue_date.isoformat() for item in monthly},
            "financial_metrics": financial_latest,
            "valuations": {item.ticker: item.trade_date.isoformat() for item in valuations},
        },
        "coverage": {
            "market": len(market) / len(tickers) if tickers else 0,
            "monthly_revenue": len(monthly) / len(tickers) if tickers else 0,
            "financial_metrics": len(financial_latest) / len(tickers) if tickers else 0,
            "valuations": len(valuations) / len(tickers) if tickers else 0,
        },
        "company_data_audit": audit,
    }


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
    db_retention = dict(db_retention or {})
    file_retention = dict(file_retention or {})
    artifact_retention = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in file_retention.items()
    }
    artifact_retention = {
        **artifact_retention,
        "path": artifact_retention.get("path"),
    }
    return {
        "policy": "latest_per_topic",
        "db": db_retention,
        "artifacts": artifact_retention,
        "old_report_versions_deleted": int(db_retention.get("old_report_versions_deleted") or 0),
        "old_report_files_deleted": int(file_retention.get("old_report_files_deleted") or 0),
    }


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
        result = _api_services_for_tasks().data_operations_api().maintenance_cleanup(
            failed_runs=bool(cleanup_payload.get("failed_runs", False)),
            orphan_report_refs=bool(cleanup_payload.get("orphan_report_refs", True)),
            latest_reports_only=bool(cleanup_payload.get("latest_reports_only", True)),
            stale_running_before=_maintenance_stale_running_before(cleanup_payload),
            runs_before=_payload_datetime(cleanup_payload, "runs_before"),
            reports_before=_payload_datetime(cleanup_payload, "reports_before"),
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
    with session_scope() as session:
        run = AnalysisRunRepository(session).start("celery", build_run_payload(payload, task_id))
        run_id = run.id
    request = ReportRequest.model_validate(payload)
    workflow = workflow_checkpoint_recorder()
    workflow.initialize(run_id, "celery_report_task", CELERY_REPORT_STEPS)
    current_step = "pre_report_refresh"
    try:
        _raise_if_cancelled(run_id)
        workflow.start_step(run_id, current_step)
        ingestion_summary = run_async_from_sync(
            _cancellable_ingestion_pipeline(run_id).pre_report_refresh(request),
            operation="celery.generate_report.pre_report_refresh",
        )
        _raise_if_cancelled(run_id)
        workflow.complete_step(
            run_id,
            current_step,
            {
                "news_count": (ingestion_summary.get("news") or {}).get("count", 0),
                "company_filing_count": (ingestion_summary.get("company_filings") or {}).get(
                    "stored_count", 0
                ),
            },
        )
        with session_scope() as session:
            AnalysisRunRepository(session).update_payload(
                run_id,
                workflow.payload_with_current_workflow(
                    run_id,
                    build_run_payload(payload, task_id, ingestion_summary),
                ),
            )
        current_step = "report_build"
        _raise_if_cancelled(run_id)
        workflow.start_step(run_id, current_step)
        report_result = ReportBuildService().build(
            request,
            source_count=(ingestion_summary.get("news") or {}).get("count", 0),
        )
        _raise_if_cancelled(run_id)
        response = report_result["response"]
        quality_gate = report_result["quality_gate"]
        workflow.complete_step(
            run_id,
            current_step,
            {
                "quality_gate_status": quality_gate.get("status"),
                "evidence_count": report_result["evidence_count"],
            },
        )
        follow_up_summary = None
        if quality_gate.get("status") != "ready":
            current_step = "follow_up_actions"
            _raise_if_cancelled(run_id)
            workflow.start_step(
                run_id, current_step, {"quality_gate_status": quality_gate.get("status")}
            )
            follow_up_actions = FollowUpActionPlanner().plan(request, quality_gate=quality_gate)
            if follow_up_actions:
                follow_up_summary = execute_follow_up_actions_sync(follow_up_actions, request)
                _raise_if_cancelled(run_id)
                ingestion_summary = {
                    **ingestion_summary,
                    "follow_up": follow_up_summary,
                }
                report_result = ReportBuildService().build(
                    request,
                    source_count=(ingestion_summary.get("news") or {}).get("count", 0),
                )
                response = report_result["response"]
                quality_gate = report_result["quality_gate"]
                _raise_if_cancelled(run_id)
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "action_count": len(follow_up_actions),
                    "stored_count": (follow_up_summary or {})
                    .get("execution_summary", {})
                    .get("stored_count"),
                    "quality_gate_status_after": quality_gate.get("status"),
                },
            )
        current_step = "report_persist"
        _raise_if_cancelled(run_id)
        workflow.start_step(
            run_id, current_step, {"quality_gate_status": quality_gate.get("status")}
        )
        with session_scope() as session:
            AnalysisRunRepository(session).update_payload(
                run_id,
                workflow.payload_with_current_workflow(
                    run_id,
                    {
                        **build_run_payload(payload, task_id, ingestion_summary),
                        "quality_gate": quality_gate,
                        "follow_up": follow_up_summary,
                        "report_execution": report_result["report_execution"],
                    },
                ),
            )
        _raise_if_cancelled(run_id)
        report_id, db_retention = _create_report_with_retention(request, response)
        record_llm_usage_from_report_execution(
            report_result.get("report_execution"),
            operation="celery_report_generation",
            report_id=report_id,
            run_id=run_id,
        )
        workflow.complete_step(run_id, current_step, {"report_id": report_id})
        file_retention = _write_report_file_with_retention(request, response)
        path = file_retention["path"]
        retention = _combined_report_retention(db_retention, file_retention)
        with session_scope() as session:
            AnalysisRunRepository(session).update_payload(
                run_id,
                workflow.complete_workflow_payload(
                    run_id,
                    {
                        **build_run_payload(payload, task_id, ingestion_summary),
                        "quality_gate": quality_gate,
                        "follow_up": follow_up_summary,
                        "report_execution": report_result["report_execution"],
                        "retention": retention,
                    },
                ),
            )
            AnalysisRunRepository(session).mark_success(run_id, report_id, str(path))
        return {
            "task_id": task_id,
            "run_id": run_id,
            "id": report_id,
            "title": response.title,
            "path": str(path),
            "generated_at": response.generated_at.isoformat(),
            "retention": retention,
        }
    except TaskCancelledError as exc:
        workflow.cancel_step(run_id, current_step, str(exc), {"cancelled": True})
        _mark_cancelled(run_id)
        return {
            "task_id": task_id,
            "run_id": run_id,
            "cancelled": True,
        }
    except Exception as exc:
        workflow.fail_step(run_id, current_step, str(exc))
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise


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
