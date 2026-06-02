from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest
from app.services.followup_actions import FollowUpActionPlanner, execute_follow_up_actions_sync
from app.services.ingestion import IngestionPipeline
from app.services.persistence import AnalysisRunRepository, ReportRepository
from app.services.report_build import ReportBuildService
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
        settings = get_settings()
        settings.report_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{response.generated_at.strftime('%Y%m%d_%H%M%S')}_{request.topic}.md"
        path = Path(settings.report_dir) / filename.replace("/", "_")
        path.write_text(response.markdown, encoding="utf-8")
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
