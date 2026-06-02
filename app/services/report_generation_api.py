from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager

from app.models.schemas import ReportRequest, ReportResponse
from app.services.ingestion import IngestionPipeline
from app.services.persistence import AnalysisRunRepository, ReportRepository
from app.services.report_generator import ReportExecutionError


class SyncReportGenerationApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
        report_repository_cls: type[ReportRepository] = ReportRepository,
        report_build_service_factory: Callable[[], object],
        count_sufficient_company_filings_func: Callable[[list[str]], int],
        ingestion_pipeline_cls: type[IngestionPipeline] | None = None,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.report_repository_cls = report_repository_cls
        self.report_build_service_factory = report_build_service_factory
        self.count_sufficient_company_filings_func = count_sufficient_company_filings_func
        self.ingestion_pipeline_cls = ingestion_pipeline_cls

    def generate(self, request: ReportRequest) -> ReportResponse:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).start(
                "api_sync",
                request.model_dump(mode="json"),
            )
            run_id = run.id
        try:
            ingestion_summary = self._pre_report_refresh(request)
            build_kwargs = {
                "company_filing_sufficient_count": self.count_sufficient_company_filings_func(request.tickers),
            }
            if ingestion_summary:
                build_kwargs["source_count"] = (ingestion_summary.get("news") or {}).get("count", 0)
            report_result = self.report_build_service_factory().build(request, **build_kwargs)
            response = report_result["response"]
            quality_gate = report_result["quality_gate"]
            with self.session_scope_factory() as session:
                report = self.report_repository_cls(session).create(request, response)
                run_repository = self.analysis_run_repository_cls(session)
                run_repository.update_payload(
                    run_id,
                    {
                        "request": request.model_dump(mode="json"),
                        "quality_gate": quality_gate,
                        "evidence_count": report_result["evidence_count"],
                        "report_execution": report_result["report_execution"],
                        **({"ingestion": ingestion_summary} if ingestion_summary else {}),
                    },
                )
                run_repository.mark_success(run_id, report.id)
            return response
        except ReportExecutionError as exc:
            self._mark_failed(run_id, str(exc))
            raise
        except Exception as exc:
            self._mark_failed(run_id, str(exc))
            raise

    def _mark_failed(self, run_id: int, error: str) -> None:
        with self.session_scope_factory() as session:
            self.analysis_run_repository_cls(session).mark_failed(run_id, error)

    def _pre_report_refresh(self, request: ReportRequest) -> dict:
        if self.ingestion_pipeline_cls is None:
            return {}
        return asyncio.run(self.ingestion_pipeline_cls().pre_report_refresh(request))
