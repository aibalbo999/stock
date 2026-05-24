from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest
from app.services.ingestion import IngestionPipeline
from app.services.persistence import AnalysisRunRepository, ReportRepository
from app.services.report_generator import ReportGenerator
from app.services.report_quality import attach_quality_gate_to_report, build_quality_gate_for_request
from app.tasks.celery_app import celery_app


def build_run_payload(payload: dict, task_id: str | None = None, ingestion: dict | None = None) -> dict:
    run_payload = {"request": payload}
    if task_id:
        run_payload["celery_task_id"] = task_id
    if ingestion is not None:
        run_payload["ingestion"] = ingestion
    return run_payload


@celery_app.task(bind=True, name="app.tasks.tasks.generate_report_task")
def generate_report_task(self, payload: dict) -> dict:
    init_db()
    task_id = getattr(self.request, "id", None)
    with session_scope() as session:
        run = AnalysisRunRepository(session).start("celery", build_run_payload(payload, task_id))
        run_id = run.id
    request = ReportRequest.model_validate(payload)
    try:
        ingestion_summary = asyncio.run(IngestionPipeline().pre_report_refresh(request))
        with session_scope() as session:
            AnalysisRunRepository(session).update_payload(
                run_id,
                build_run_payload(payload, task_id, ingestion_summary),
            )
        generator = ReportGenerator()
        response = generator.generate(request)
        quality_gate = build_quality_gate_for_request(
            request,
            documents=generator.last_evidence_documents,
            source_count=max(
                (ingestion_summary.get("news") or {}).get("count", 0),
                len(generator.last_evidence_documents),
            ),
        )
        response = attach_quality_gate_to_report(response, quality_gate)
        with session_scope() as session:
            AnalysisRunRepository(session).update_payload(
                run_id,
                {
                    **build_run_payload(payload, task_id, ingestion_summary),
                    "quality_gate": quality_gate,
                },
            )
        with session_scope() as session:
            report = ReportRepository(session).create(request, response)
            report_id = report.id
        settings = get_settings()
        settings.report_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{response.generated_at.strftime('%Y%m%d_%H%M%S')}_{request.topic}.md"
        path = Path(settings.report_dir) / filename.replace("/", "_")
        path.write_text(response.markdown, encoding="utf-8")
        with session_scope() as session:
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
        with session_scope() as session:
            AnalysisRunRepository(session).mark_failed(run_id, str(exc))
        raise
