from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.discovered_candidate_filings import (
    candidate_filing_revalidation_tickers as candidate_filing_revalidation_tickers,
    company_filing_timeout_result as company_filing_timeout_result,
    should_revalidate_candidate_filings as should_revalidate_candidate_filings,
)
from app.services.discovered_pipeline_candidates import DiscoveredPipelineCandidateMixin
from app.services.discovered_pipeline_report_stage import (
    DiscoveredAutoFollowUpInput,
    DiscoveredPipelineReportStageMixin,
    DiscoveredReportStageInput,
)
from app.services.discovered_pipeline_resume import DiscoveredPipelineResumeMixin
from app.services.discovered_pipeline_run_state import DiscoveredPipelineRunStateMixin
from app.services.report_generator import ReportExecutionError
from app.services.task_cancellation import TaskCancelledError


class DiscoveredTopicPipelineService(
    DiscoveredPipelineRunStateMixin,
    DiscoveredPipelineResumeMixin,
    DiscoveredPipelineReportStageMixin,
    DiscoveredPipelineCandidateMixin,
):
    def __init__(
        self,
        *,
        session_scope_factory: Callable,
        analysis_run_repository_cls: type,
        report_repository_cls: type,
        company_filing_repository_cls: type,
        topic_discovery_service_cls: type,
        topic_discovery_plan_cls: type,
        supply_chain_whitelist_cls: type,
        workflow_recorder_factory: Callable[[], Any],
        discovered_market_data_service_factory: Callable[[], Any],
        discovered_report_builder_service_factory: Callable[[], Any],
        discover_topic_with_timeout_func: Callable[..., Awaitable[dict]],
        discovery_fetch_settings_func: Callable[[Any], tuple[int, int, int]],
        discovery_document_limit_func: Callable[[Any, int], int],
        run_topic_discovery_ingestion_func: Callable[..., Awaitable[dict]],
        should_revalidate_candidate_filings_func: Callable[[list[dict]], bool],
        candidate_filing_revalidation_tickers_func: Callable[[list[dict], Any], list[str]],
        company_filing_timeout_result_func: Callable[[list[str], Exception, str], dict],
        dedupe_documents_func: Callable[[list], list],
        apply_company_filing_gate_func: Callable[[list[dict]], list[dict]],
        summarize_candidate_support_payload_func: Callable[[list[dict]], dict],
        summarize_candidate_support_func: Callable[[list], dict],
        safe_update_run_success_func: Callable[[int, dict, int], bool],
        safe_mark_run_failed_func: Callable[[int, str], None],
        auto_follow_up_func: Callable[[int], Awaitable[dict]],
        workflow_steps: list[str],
        task_cancellation_checker: Callable[[int], None] | None = None,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.report_repository_cls = report_repository_cls
        self.company_filing_repository_cls = company_filing_repository_cls
        self.topic_discovery_service_cls = topic_discovery_service_cls
        self.topic_discovery_plan_cls = topic_discovery_plan_cls
        self.supply_chain_whitelist_cls = supply_chain_whitelist_cls
        self.workflow_recorder_factory = workflow_recorder_factory
        self.discovered_market_data_service_factory = discovered_market_data_service_factory
        self.discovered_report_builder_service_factory = discovered_report_builder_service_factory
        self.discover_topic_with_timeout_func = discover_topic_with_timeout_func
        self.discovery_fetch_settings_func = discovery_fetch_settings_func
        self.discovery_document_limit_func = discovery_document_limit_func
        self.run_topic_discovery_ingestion_func = run_topic_discovery_ingestion_func
        self.should_revalidate_candidate_filings_func = should_revalidate_candidate_filings_func
        self.candidate_filing_revalidation_tickers_func = candidate_filing_revalidation_tickers_func
        self.company_filing_timeout_result_func = company_filing_timeout_result_func
        self.dedupe_documents_func = dedupe_documents_func
        self.apply_company_filing_gate_func = apply_company_filing_gate_func
        self.summarize_candidate_support_payload_func = summarize_candidate_support_payload_func
        self.summarize_candidate_support_func = summarize_candidate_support_func
        self.safe_update_run_success_func = safe_update_run_success_func
        self.safe_mark_run_failed_func = safe_mark_run_failed_func
        self.auto_follow_up_func = auto_follow_up_func
        self.workflow_steps = workflow_steps
        self.task_cancellation_checker = task_cancellation_checker

    async def run(self, payload: Any, *, celery_task_id: str | None = None) -> dict:
        run_id = self._start_run(payload)
        workflow = self.workflow_recorder_factory()
        workflow.initialize(run_id, "ai_discovered_topic_pipeline", self.workflow_steps)
        if celery_task_id:
            self._attach_celery_task_id(run_id, celery_task_id)
        current_step = "topic_discovery"
        try:
            self._check_cancelled(run_id)
            service = self.topic_discovery_service_cls()
            workflow.start_step(run_id, current_step, {"topic": payload.topic})
            discovery = await self.discover_topic_with_timeout_func(service, payload.topic)
            self._check_cancelled(run_id)
            plan = self.topic_discovery_plan_cls.model_validate(discovery["plan"])
            limit_per_query, evidence_limit, max_queries = self.discovery_fetch_settings_func(
                payload
            )
            document_limit = self.discovery_document_limit_func(payload, evidence_limit)
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "fallback": bool(discovery.get("fallback")),
                    "plan_quality_status": (discovery.get("plan_quality") or {}).get("status"),
                    "subtopic_count": len(plan.subtopics),
                    "candidate_count": len(plan.candidate_companies),
                },
            )
            self._checkpoint_stage_payload(
                run_id,
                workflow,
                {
                    "pipeline_request": self._payload_model_dump(payload),
                    "discovery": discovery,
                    "discovery_fetch_settings": {
                        "limit_per_query": limit_per_query,
                        "evidence_limit": evidence_limit,
                        "max_queries": max_queries,
                        "document_limit": document_limit,
                    },
                },
            )
            current_step = "source_ingestion"
            self._check_cancelled(run_id)
            workflow.start_step(
                run_id,
                current_step,
                {
                    "limit_per_query": limit_per_query,
                    "evidence_limit": evidence_limit,
                    "max_queries": max_queries,
                },
            )
            discovery_ingestion = await self.run_topic_discovery_ingestion_func(
                payload,
                service,
                plan,
                limit_per_query,
                evidence_limit,
                max_queries,
                document_limit=document_limit,
            )
            self._check_cancelled(run_id)
            urls = discovery_ingestion["urls"]
            end_date = discovery_ingestion["end_date"]
            documents = discovery_ingestion["documents"]
            fixed_source_ingestion = discovery_ingestion["fixed_source_ingestion"]
            dynamic_query_ingestion = discovery_ingestion["dynamic_query_ingestion"]
            ingestion_results = discovery_ingestion["ingestion_results"]
            source_audit = discovery_ingestion["source_audit"]
            candidate_payload = [
                candidate.model_dump() for candidate in discovery_ingestion["candidates"]
            ]
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "query_count": len(urls),
                    "document_count": len(documents),
                    "stored_count": source_audit.get("total_stored_count"),
                    "candidate_count": len(candidate_payload),
                },
            )
            self._checkpoint_stage_payload(
                run_id,
                workflow,
                {
                    "queries": urls,
                    "discovery_end_date": self._json_safe(end_date),
                    "source_documents": self._documents_payload(documents),
                    "fixed_source_ingestion": fixed_source_ingestion,
                    "dynamic_query_ingestion": dynamic_query_ingestion,
                    "ingestion": ingestion_results,
                    "source_audit": source_audit,
                    "candidate_whitelist": candidate_payload,
                },
            )
            current_step = "candidate_revalidation"
            self._check_cancelled(run_id)
            workflow.start_step(run_id, current_step, {"candidate_count": len(candidate_payload)})
            candidate_filing_ingestion, candidate_payload, documents = self._revalidate_candidates(
                payload,
                service,
                plan,
                source_audit,
                candidate_payload,
                documents,
            )
            self._check_cancelled(run_id)
            candidate_stage = self._finalize_candidate_revalidation_stage(
                candidate_filing_ingestion=candidate_filing_ingestion,
                candidate_payload=candidate_payload,
                documents=documents,
                source_audit=source_audit,
            )
            candidate_filing_ingestion = candidate_stage.candidate_filing_ingestion
            candidate_payload = candidate_stage.candidate_payload
            documents = candidate_stage.documents
            source_audit = candidate_stage.source_audit
            promoted_tickers = candidate_stage.promoted_tickers
            company_filing_ingestion = candidate_stage.company_filing_ingestion
            dynamic_whitelist = self.supply_chain_whitelist_cls.from_candidate_whitelist(
                candidate_payload
            )
            workflow.complete_step(
                run_id,
                current_step,
                candidate_stage.workflow_summary(),
            )
            self._checkpoint_stage_payload(
                run_id,
                workflow,
                candidate_stage.checkpoint_updates(self._documents_payload),
            )

            current_step = "market_data_refresh"
            self._check_cancelled(run_id)
            workflow.start_step(run_id, current_step, {"promoted_count": len(promoted_tickers)})
            market_data = await self._discovered_market_data_service(
                run_id
            ).fetch_and_persist_for_discovery(
                payload,
                promoted_tickers,
                end_date,
            )
            self._check_cancelled(run_id)
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "market_count": len(market_data["snapshots"]),
                    "monthly_revenue_count": len(market_data["latest_monthly_revenues"]),
                    "financial_metrics_count": len(market_data["financial_metrics"]),
                    "valuation_count": len(market_data["valuations"]),
                },
            )
            self._checkpoint_stage_payload(
                run_id,
                workflow,
                {"market_data": self._market_data_payload(market_data)},
            )
            current_step = "report_build"
            self._check_cancelled(run_id)
            workflow.start_step(run_id, current_step, {"promoted_count": len(promoted_tickers)})
            report_stage = self._build_report_stage(
                DiscoveredReportStageInput(
                    run_id=run_id,
                    payload=payload,
                    promoted_tickers=promoted_tickers,
                    dynamic_whitelist=dynamic_whitelist,
                    documents=documents,
                    evidence_limit=evidence_limit,
                    source_audit=source_audit,
                    discovery=discovery,
                    urls=urls,
                    ingestion_results=ingestion_results,
                    fixed_source_ingestion=fixed_source_ingestion,
                    dynamic_query_ingestion=dynamic_query_ingestion,
                    candidate_filing_ingestion=candidate_filing_ingestion,
                    company_filing_ingestion=company_filing_ingestion,
                    candidate_payload=candidate_payload,
                    market_data=market_data,
                )
            )
            self._check_cancelled(run_id)
            workflow.complete_step(run_id, current_step, report_stage.workflow_summary())
            self._checkpoint_report_build_payload(run_id, workflow, report_stage.run_payload)
            current_step = "auto_follow_up"
            self._check_cancelled(run_id)
            workflow.start_step(run_id, current_step, {"report_id": report_stage.report_id})
            return await self._complete_report_auto_follow_up_stage(
                DiscoveredAutoFollowUpInput(
                    run_id=run_id,
                    workflow=workflow,
                    pipeline_payload=payload,
                    report_stage=report_stage,
                    discovery=discovery,
                    queries=urls,
                    fixed_source_ingestion=fixed_source_ingestion,
                    dynamic_query_ingestion=dynamic_query_ingestion,
                    candidate_filing_ingestion=candidate_filing_ingestion,
                    company_filing_ingestion=company_filing_ingestion,
                    source_audit=source_audit,
                    candidate_payload=candidate_payload,
                    promoted_tickers=promoted_tickers,
                )
            )
        except TaskCancelledError as exc:
            workflow.cancel_step(run_id, current_step, str(exc), {"cancelled": True})
            self._mark_run_cancelled(run_id, str(exc))
            raise
        except Exception as exc:
            workflow.fail_step(run_id, current_step, str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise


__all__ = [
    "DiscoveredTopicPipelineService",
    "ReportExecutionError",
    "candidate_filing_revalidation_tickers",
    "company_filing_timeout_result",
    "should_revalidate_candidate_filings",
]
