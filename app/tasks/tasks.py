from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.core.time import today_taipei
from app.core.config import get_settings
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.company_data_audit import audit_company_data
from app.services.followup_actions import FollowUpActionPlanner, execute_follow_up_actions_sync
from app.services.ingestion import IngestionPipeline
from app.services.persistence import (
    AnalysisRunRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ReportRepository,
    ValuationMetricRepository,
)
from app.services.report_build import ReportBuildService
from app.services.report_followup import (
    candidate_audit_from_run_payload,
    parse_run_payload,
    plan_quality_from_quality_gate,
    summarize_candidate_support_payload,
)
from app.services.report_followup_context import ReportFollowUpContextService
from app.services.whitelist import SupplyChainWhitelist
from app.services.workflow_checkpoint import CELERY_REPORT_STEPS, WorkflowCheckpointRecorder
from app.tasks.celery_app import celery_app


def build_run_payload(payload: dict, task_id: str | None = None, ingestion: dict | None = None) -> dict:
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


def _normalize_tickers(tickers: list[Any] | tuple[Any, ...] | None) -> list[str]:
    values = [str(ticker).strip() for ticker in tickers or [] if str(ticker).strip()]
    return list(dict.fromkeys(values))


def _json_tickers(value: str | None) -> list[str]:
    try:
        payload = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return _normalize_tickers(payload if isinstance(payload, list) else [])


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
        for item in (context.get("candidate_whitelist") or candidate_audit_from_run_payload(run_payload))
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
        schedule_payload.get("lookback_days")
        or getattr(request, "lookback_days", None)
        or 120
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


async def _refresh_after_close_data(target: dict, schedule_payload: dict) -> dict:
    today = today_taipei()
    request = target["request"]
    tickers = target["tickers"]
    lookback_days = max(int(getattr(request, "lookback_days", 120) or 120), 120)
    pipeline = IngestionPipeline()
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
    with session_scope() as session:
        report = ReportRepository(session).create(request, response)
        report_id = report.id
    path = _write_report_file(request, response)
    return {
        "status": "generated",
        "report_id": report_id,
        "path": str(path),
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
    settings = get_settings()
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{response.generated_at.strftime('%Y%m%d_%H%M%S')}_{request.topic}.md"
    path = Path(settings.report_dir) / filename.replace("/", "_")
    path.write_text(response.markdown, encoding="utf-8")
    return path


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
        workflow.start_step(run_id, current_step)
        ingestion_summary = asyncio.run(IngestionPipeline().pre_report_refresh(request))
        workflow.complete_step(
            run_id,
            current_step,
            {
                "news_count": (ingestion_summary.get("news") or {}).get("count", 0),
                "company_filing_count": (ingestion_summary.get("company_filings") or {}).get("stored_count", 0),
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
        workflow.start_step(run_id, current_step)
        report_result = ReportBuildService().build(
            request,
            source_count=(ingestion_summary.get("news") or {}).get("count", 0),
        )
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
            workflow.start_step(run_id, current_step, {"quality_gate_status": quality_gate.get("status")})
            follow_up_actions = FollowUpActionPlanner().plan(request, quality_gate=quality_gate)
            if follow_up_actions:
                follow_up_summary = execute_follow_up_actions_sync(follow_up_actions, request)
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
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "action_count": len(follow_up_actions),
                    "stored_count": (follow_up_summary or {}).get("execution_summary", {}).get("stored_count"),
                    "quality_gate_status_after": quality_gate.get("status"),
                },
            )
        current_step = "report_persist"
        workflow.start_step(run_id, current_step, {"quality_gate_status": quality_gate.get("status")})
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
        with session_scope() as session:
            report = ReportRepository(session).create(request, response)
            report_id = report.id
        workflow.complete_step(run_id, current_step, {"report_id": report_id})
        path = _write_report_file(request, response)
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
        target = _latest_report_update_target(schedule_payload)
        refresh = asyncio.run(_refresh_after_close_data(target, schedule_payload))
        coverage = _coverage_after_close_update(target)
        rerun_report = None
        if bool(schedule_payload.get("rerun_report", True)):
            rerun_report = _rerun_after_close_report(target)
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
    except Exception as exc:
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise
