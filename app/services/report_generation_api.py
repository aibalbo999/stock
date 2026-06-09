from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from app.models.schemas import ReportRequest, ReportResponse
from app.services.analysis_run_repository import AnalysisRunRepository
from app.services.llm_usage import record_llm_usage_from_report_execution
from app.services.report_generator import ReportExecutionError
from app.services.report_quality import should_recover_market_data_quality
from app.services.report_repository import ReportRepository


class SyncReportGenerationApiService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
        report_repository_cls: type[ReportRepository] = ReportRepository,
        report_build_service_factory: Callable[[], object],
        count_sufficient_company_filings_func: Callable[[list[str]], int],
        ingestion_pipeline_cls: type | None = None,
        quality_recovery_pipeline_cls: type | None = None,
        sync_pre_refresh_requested: bool = False,
        sync_quality_recovery_requested: bool = False,
        market_quality_recovery_required_func: Callable[
            [dict | None], bool
        ] = should_recover_market_data_quality,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.report_repository_cls = report_repository_cls
        self.report_build_service_factory = report_build_service_factory
        self.count_sufficient_company_filings_func = count_sufficient_company_filings_func
        self.sync_pre_refresh_requested = bool(
            sync_pre_refresh_requested or ingestion_pipeline_cls is not None
        )
        self.sync_quality_recovery_requested = bool(
            sync_quality_recovery_requested or quality_recovery_pipeline_cls is not None
        )
        self.market_quality_recovery_required_func = market_quality_recovery_required_func

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
                "company_filing_sufficient_count": self.count_sufficient_company_filings_func(
                    request.tickers
                ),
            }
            news_count = (ingestion_summary.get("news") or {}).get("count")
            if news_count is not None:
                build_kwargs["source_count"] = news_count
            report_result = self.report_build_service_factory().build(request, **build_kwargs)
            report_result, quality_recovery = self._recover_market_quality_if_needed(
                request,
                report_result,
                build_kwargs,
            )
            response = report_result["response"]
            quality_gate = report_result["quality_gate"]
            with self.session_scope_factory() as session:
                report = self.report_repository_cls(session).create(request, response)
                run_repository = self.analysis_run_repository_cls(session)
                run_payload = {
                    "request": request.model_dump(mode="json"),
                    "quality_gate": quality_gate,
                    "evidence_count": report_result["evidence_count"],
                    "report_execution": report_result["report_execution"],
                    **({"ingestion": ingestion_summary} if ingestion_summary else {}),
                }
                if quality_recovery is not None:
                    run_payload["quality_recovery"] = quality_recovery
                run_repository.update_payload(
                    run_id,
                    run_payload,
                )
                run_repository.mark_success(run_id, report.id)
            record_llm_usage_from_report_execution(
                report_result.get("report_execution"),
                report_id=report.id,
                run_id=run_id,
                session_scope_factory=self.session_scope_factory,
            )
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
        if not self.sync_pre_refresh_requested:
            return {}
        return _background_task_required_payload(
            reason="sync_report_pre_refresh_requires_background_task",
            requested_tickers=request.tickers,
        )

    def _recover_market_quality_if_needed(
        self,
        request: ReportRequest,
        report_result: dict,
        build_kwargs: dict,
    ) -> tuple[dict, dict | None]:
        quality_gate = report_result.get("quality_gate") or {}
        if not self.market_quality_recovery_required_func(quality_gate):
            return report_result, None
        if not request.tickers:
            return report_result, {"status": "skipped", "reason": "refresh_market_unavailable"}
        if self.sync_quality_recovery_requested:
            return report_result, {
                **_background_task_required_payload(
                    reason="sync_report_quality_recovery_requires_background_task",
                    requested_tickers=request.tickers,
                ),
                "quality_gate_before": quality_gate,
            }
        return report_result, {
            "status": "skipped",
            "reason": "sync_report_quality_recovery_disabled",
            "action": "refresh_market",
            "quality_gate_before": quality_gate,
        }


def _background_task_required_payload(*, reason: str, requested_tickers: list[str]) -> dict:
    return {
        "status": "skipped",
        "reason": reason,
        "action": "use_background_task",
        "requested_tickers": list(requested_tickers),
        "background_task_endpoint": "POST /reports/generate_async",
        "data_operation_endpoint": "POST /tasks/data-operation",
        "data_operation_payload": {
            "operation": "market_refresh",
            "payload": {"tickers": list(requested_tickers)},
        },
    }
