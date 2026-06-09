from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.discovered_candidate_filings import (
    candidate_filing_revalidation_tickers as candidate_filing_revalidation_tickers,
    company_filing_timeout_result as company_filing_timeout_result,
    should_revalidate_candidate_filings as should_revalidate_candidate_filings,
)
from app.services import discovered_market_payload
from app.services.discovered_pipeline_checkpoints import (
    date_from_checkpoint,
    documents_from_payload,
    documents_payload,
    json_safe,
    parse_checkpoint_payload_json,
    payload_from_checkpoint,
    payload_model_dump,
    resume_report_id,
)
from app.services.discovered_pipeline_candidates import DiscoveredPipelineCandidateMixin
from app.services.discovered_pipeline_results import discovered_pipeline_result_payload
from app.services.discovered_pipeline_report_stage import DiscoveredPipelineReportStageMixin
from app.services.discovered_pipeline_run_state import DiscoveredPipelineRunStateMixin
from app.services.report_generator import ReportExecutionError
from app.services.report_followup import matching_follow_up_rerun_report_id
from app.services.task_cancellation import TaskCancelledError
from app.services.workflow_checkpoint import WorkflowCheckpointRecorder


class DiscoveredTopicPipelineService(
    DiscoveredPipelineRunStateMixin,
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
            report_result = self.discovered_report_builder_service_factory().build_and_store_report(
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
                run_id=run_id,
            )
            self._check_cancelled(run_id)
            response = report_result["response"]
            request = report_result.get("request") or payload
            report_id = report_result["report_id"]
            quality_gate = report_result["quality_gate"]
            report_execution = report_result["report_execution"]
            run_payload = report_result["run_payload"]
            run_payload = {**run_payload, "report_id": report_id}
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "report_id": report_id,
                    "quality_gate_status": quality_gate.get("status"),
                    "evidence_count": report_execution.get("evidence_count"),
                },
            )
            self._checkpoint_report_build_payload(run_id, workflow, run_payload)
            current_step = "auto_follow_up"
            self._check_cancelled(run_id)
            workflow.start_step(run_id, current_step, {"report_id": report_id})
            run_payload = workflow.complete_workflow_payload(run_id, run_payload)
            run_record_updated = self.safe_update_run_success_func(run_id, run_payload, report_id)
            auto_follow_up = await self.auto_follow_up_func(report_id)
            self._check_cancelled(run_id)
            active_report_id = (
                matching_follow_up_rerun_report_id(
                    auto_follow_up,
                    report_id,
                    source_topic=payload.topic,
                    source_tickers=promoted_tickers,
                )
                or report_id
            )
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "status": auto_follow_up.get("status"),
                    "rerun_report_id": active_report_id if active_report_id != report_id else None,
                },
            )
            return discovered_pipeline_result_payload(
                run_id=run_id,
                run_record_updated=run_record_updated,
                report_id=report_id,
                active_report_id=active_report_id,
                auto_follow_up=auto_follow_up,
                discovery=discovery,
                queries=urls,
                fixed_source_ingestion=fixed_source_ingestion,
                dynamic_query_ingestion=dynamic_query_ingestion,
                candidate_filing_ingestion=candidate_filing_ingestion,
                company_filing_ingestion=company_filing_ingestion,
                source_audit=source_audit,
                candidate_whitelist=candidate_payload,
                promoted_tickers=promoted_tickers,
                run_payload=run_payload,
                quality_gate=quality_gate,
                report_execution=report_execution,
                request=request.model_dump(mode="json"),
                topic=request.topic,
                report=response.model_dump(mode="json"),
            )
        except TaskCancelledError as exc:
            workflow.cancel_step(run_id, current_step, str(exc), {"cancelled": True})
            self._mark_run_cancelled(run_id, str(exc))
            raise
        except Exception as exc:
            workflow.fail_step(run_id, current_step, str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise

    async def resume(self, run_id: int) -> dict:
        run, payload, workflow = self._load_resumable_discovered_run(run_id)
        resume = (
            workflow.get("resume")
            if isinstance(workflow.get("resume"), dict)
            else WorkflowCheckpointRecorder.resume_state(workflow)
        )
        resume_from_step = str(resume.get("resume_from_step") or "")
        if resume_from_step == "topic_discovery":
            self._mark_run_running(run_id)
            workflow_recorder = self.workflow_recorder_factory()
            try:
                payload = await self._resume_topic_discovery_stage(
                    run_id, workflow_recorder, payload
                )
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "topic_discovery", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
            return await self._resume_after_source_ingestion(
                run_id,
                workflow_recorder,
                payload,
                resume_origin="topic_discovery",
            )
        if resume_from_step == "source_ingestion":
            self._mark_run_running(run_id)
            workflow_recorder = self.workflow_recorder_factory()
            return await self._resume_after_source_ingestion(
                run_id,
                workflow_recorder,
                payload,
                resume_origin="source_ingestion",
            )
        if resume_from_step == "candidate_revalidation":
            self._mark_run_running(run_id)
            workflow_recorder = self.workflow_recorder_factory()
            try:
                payload = self._resume_candidate_revalidation_stage(
                    run_id, workflow_recorder, payload
                )
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "candidate_revalidation", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
            try:
                payload = await self._resume_market_data_refresh_stage(
                    run_id, workflow_recorder, payload
                )
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "market_data_refresh", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
            try:
                return await self._resume_report_build(
                    run_id,
                    workflow_recorder,
                    payload,
                    resume_origin="candidate_revalidation",
                )
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "report_build", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
        if resume_from_step == "market_data_refresh":
            self._mark_run_running(run_id)
            workflow_recorder = self.workflow_recorder_factory()
            try:
                payload = await self._resume_market_data_refresh_stage(
                    run_id, workflow_recorder, payload
                )
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "market_data_refresh", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
            try:
                return await self._resume_report_build(
                    run_id,
                    workflow_recorder,
                    payload,
                    resume_origin="market_data_refresh",
                )
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "report_build", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
        if resume_from_step == "report_build":
            self._mark_run_running(run_id)
            workflow_recorder = self.workflow_recorder_factory()
            try:
                return await self._resume_report_build(run_id, workflow_recorder, payload)
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "report_build", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
        if resume_from_step != "auto_follow_up":
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline can currently resume only from topic_discovery, "
                "source_ingestion, candidate_revalidation, market_data_refresh, report_build, or auto_follow_up; "
                f"got {resume_from_step or 'unknown'}"
            )
        report_id = self._resume_report_id(run, payload)
        self._mark_run_running(run_id)
        workflow_recorder = self.workflow_recorder_factory()
        current_step = "auto_follow_up"
        try:
            workflow_recorder.start_step(
                run_id,
                current_step,
                {"report_id": report_id, "resumed": True},
            )
            run_payload = {**payload, "report_id": report_id}
            request_payload = (
                payload.get("request") if isinstance(payload.get("request"), dict) else {}
            )
            candidate_payload = (
                payload.get("candidate_whitelist")
                if isinstance(payload.get("candidate_whitelist"), list)
                else []
            )
            promoted_tickers = request_payload.get(
                "tickers"
            ) or self._promoted_tickers_from_candidates(candidate_payload)
            run_record_updated = self.safe_update_run_success_func(
                run_id,
                workflow_recorder.complete_workflow_payload(run_id, run_payload),
                report_id,
            )
            auto_follow_up = await self.auto_follow_up_func(report_id)
            active_report_id = (
                matching_follow_up_rerun_report_id(
                    auto_follow_up,
                    report_id,
                    source_topic=request_payload.get("topic"),
                    source_tickers=request_payload.get("tickers") or promoted_tickers,
                )
                or report_id
            )
            workflow_recorder.complete_step(
                run_id,
                current_step,
                {
                    "status": auto_follow_up.get("status"),
                    "rerun_report_id": active_report_id if active_report_id != report_id else None,
                    "resumed": True,
                },
            )
            response = self._load_report_response(report_id)
            return discovered_pipeline_result_payload(
                run_id=run_id,
                run_record_updated=run_record_updated,
                report_id=report_id,
                active_report_id=active_report_id,
                auto_follow_up=auto_follow_up,
                discovery=payload.get("discovery") or {},
                queries=payload.get("queries") or [],
                fixed_source_ingestion=payload.get("fixed_source_ingestion") or {},
                dynamic_query_ingestion=payload.get("dynamic_query_ingestion") or [],
                candidate_filing_ingestion=payload.get("candidate_filing_ingestion"),
                company_filing_ingestion=payload.get("company_filing_ingestion") or {},
                source_audit=payload.get("source_audit") or {},
                candidate_whitelist=candidate_payload,
                promoted_tickers=promoted_tickers,
                run_payload=payload,
                quality_gate=payload.get("quality_gate") or {},
                report_execution=payload.get("report_execution") or {},
                request=request_payload,
                topic=request_payload.get("topic") or payload.get("topic"),
                report=response.model_dump(mode="json"),
                resumed_from_step=current_step,
            )
        except Exception as exc:
            workflow_recorder.fail_step(run_id, current_step, str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise

    async def _resume_after_source_ingestion(
        self,
        run_id: int,
        workflow_recorder: Any,
        payload: dict,
        *,
        resume_origin: str,
    ) -> dict:
        try:
            payload = await self._resume_source_ingestion_stage(run_id, workflow_recorder, payload)
        except Exception as exc:
            workflow_recorder.fail_step(run_id, "source_ingestion", str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise
        try:
            payload = self._resume_candidate_revalidation_stage(run_id, workflow_recorder, payload)
        except Exception as exc:
            workflow_recorder.fail_step(run_id, "candidate_revalidation", str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise
        try:
            payload = await self._resume_market_data_refresh_stage(
                run_id, workflow_recorder, payload
            )
        except Exception as exc:
            workflow_recorder.fail_step(run_id, "market_data_refresh", str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise
        try:
            return await self._resume_report_build(
                run_id,
                workflow_recorder,
                payload,
                resume_origin=resume_origin,
            )
        except Exception as exc:
            workflow_recorder.fail_step(run_id, "report_build", str(exc))
            self.safe_mark_run_failed_func(run_id, str(exc))
            raise

    async def _resume_topic_discovery_stage(
        self, run_id: int, workflow: Any, checkpoint: dict
    ) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        service = self.topic_discovery_service_cls()
        current_step = "topic_discovery"
        workflow.start_step(run_id, current_step, {"topic": payload.topic, "resumed": True})
        discovery = await self.discover_topic_with_timeout_func(service, payload.topic)
        plan = self.topic_discovery_plan_cls.model_validate(discovery["plan"])
        limit_per_query, evidence_limit, max_queries = self.discovery_fetch_settings_func(payload)
        document_limit = self.discovery_document_limit_func(payload, evidence_limit)
        workflow.complete_step(
            run_id,
            current_step,
            {
                "fallback": bool(discovery.get("fallback")),
                "plan_quality_status": (discovery.get("plan_quality") or {}).get("status"),
                "subtopic_count": len(plan.subtopics),
                "candidate_count": len(plan.candidate_companies),
                "resumed": True,
            },
        )
        updates = {
            "pipeline_request": self._payload_model_dump(payload),
            "discovery": discovery,
            "discovery_fetch_settings": {
                "limit_per_query": limit_per_query,
                "evidence_limit": evidence_limit,
                "max_queries": max_queries,
                "document_limit": document_limit,
            },
        }
        self._checkpoint_stage_payload(run_id, workflow, updates)
        return {**checkpoint, **self._json_safe(updates)}

    async def _resume_source_ingestion_stage(
        self, run_id: int, workflow: Any, checkpoint: dict
    ) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        service = self.topic_discovery_service_cls()
        discovery = (
            checkpoint.get("discovery") if isinstance(checkpoint.get("discovery"), dict) else {}
        )
        if not isinstance(discovery.get("plan"), dict):
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume requires discovery.plan"
            )
        plan = self.topic_discovery_plan_cls.model_validate(discovery["plan"])
        settings = self._discovery_fetch_settings_from_checkpoint(payload, checkpoint)
        limit_per_query = settings["limit_per_query"]
        evidence_limit = settings["evidence_limit"]
        max_queries = settings["max_queries"]
        document_limit = settings["document_limit"]
        current_step = "source_ingestion"
        workflow.start_step(
            run_id,
            current_step,
            {
                "limit_per_query": limit_per_query,
                "evidence_limit": evidence_limit,
                "max_queries": max_queries,
                "resumed": True,
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
        urls = discovery_ingestion["urls"]
        end_date = discovery_ingestion["end_date"]
        documents = discovery_ingestion["documents"]
        fixed_source_ingestion = discovery_ingestion["fixed_source_ingestion"]
        dynamic_query_ingestion = discovery_ingestion["dynamic_query_ingestion"]
        ingestion_results = discovery_ingestion["ingestion_results"]
        source_audit = discovery_ingestion["source_audit"]
        candidate_payload = [
            candidate.model_dump() if hasattr(candidate, "model_dump") else dict(candidate)
            for candidate in discovery_ingestion["candidates"]
        ]
        workflow.complete_step(
            run_id,
            current_step,
            {
                "query_count": len(urls),
                "document_count": len(documents),
                "stored_count": source_audit.get("total_stored_count"),
                "candidate_count": len(candidate_payload),
                "resumed": True,
            },
        )
        updates = {
            "queries": urls,
            "discovery_end_date": self._json_safe(end_date),
            "source_documents": self._documents_payload(documents),
            "fixed_source_ingestion": fixed_source_ingestion,
            "dynamic_query_ingestion": dynamic_query_ingestion,
            "ingestion": ingestion_results,
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
        }
        self._checkpoint_stage_payload(run_id, workflow, updates)
        return {**checkpoint, **self._json_safe(updates)}

    def _resume_candidate_revalidation_stage(
        self, run_id: int, workflow: Any, checkpoint: dict
    ) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        service = self.topic_discovery_service_cls()
        discovery = (
            checkpoint.get("discovery") if isinstance(checkpoint.get("discovery"), dict) else {}
        )
        if not isinstance(discovery.get("plan"), dict):
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume requires discovery.plan"
            )
        plan = self.topic_discovery_plan_cls.model_validate(discovery["plan"])
        documents = self._documents_from_payload(checkpoint.get("source_documents") or [])
        source_audit = (
            checkpoint.get("source_audit")
            if isinstance(checkpoint.get("source_audit"), dict)
            else {}
        )
        candidate_payload = (
            checkpoint.get("candidate_whitelist")
            if isinstance(checkpoint.get("candidate_whitelist"), list)
            else []
        )
        if not candidate_payload:
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume requires candidate_whitelist"
            )
        current_step = "candidate_revalidation"
        workflow.start_step(
            run_id,
            current_step,
            {"candidate_count": len(candidate_payload), "resumed": True},
        )
        candidate_filing_ingestion, candidate_payload, documents = self._revalidate_candidates(
            payload,
            service,
            plan,
            source_audit,
            candidate_payload,
            documents,
        )
        candidate_stage = self._finalize_candidate_revalidation_stage(
            candidate_filing_ingestion=candidate_filing_ingestion,
            candidate_payload=candidate_payload,
            documents=documents,
            source_audit=source_audit,
        )
        promoted_tickers = candidate_stage.promoted_tickers
        if not promoted_tickers:
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume produced no promoted_tickers"
            )
        workflow.complete_step(
            run_id,
            current_step,
            candidate_stage.workflow_summary(resumed=True),
        )
        updates = candidate_stage.checkpoint_updates(self._documents_payload)
        self._checkpoint_stage_payload(run_id, workflow, updates)
        return {**checkpoint, **self._json_safe(updates)}

    async def _resume_market_data_refresh_stage(
        self, run_id: int, workflow: Any, checkpoint: dict
    ) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        promoted_tickers = (
            checkpoint.get("promoted_tickers")
            if isinstance(checkpoint.get("promoted_tickers"), list)
            else []
        )
        if not promoted_tickers:
            promoted_tickers = self._promoted_tickers_from_candidates(
                checkpoint.get("candidate_whitelist")
                if isinstance(checkpoint.get("candidate_whitelist"), list)
                else []
            )
        if not promoted_tickers:
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume requires promoted_tickers"
            )
        end_date = self._date_from_checkpoint(checkpoint.get("discovery_end_date"))
        current_step = "market_data_refresh"
        workflow.start_step(
            run_id,
            current_step,
            {"promoted_count": len(promoted_tickers), "resumed": True},
        )
        market_data = await self._discovered_market_data_service(
            run_id
        ).fetch_and_persist_for_discovery(
            payload,
            promoted_tickers,
            end_date,
        )
        workflow.complete_step(
            run_id,
            current_step,
            {
                "market_count": len(market_data["snapshots"]),
                "monthly_revenue_count": len(market_data["latest_monthly_revenues"]),
                "financial_metrics_count": len(market_data["financial_metrics"]),
                "valuation_count": len(market_data["valuations"]),
                "resumed": True,
            },
        )
        updates = {"market_data": self._market_data_payload(market_data)}
        self._checkpoint_stage_payload(run_id, workflow, updates)
        return {**checkpoint, **self._json_safe(updates)}

    _parse_payload = staticmethod(parse_checkpoint_payload_json)
    _resume_report_id = staticmethod(resume_report_id)
    _payload_model_dump = staticmethod(payload_model_dump)
    _payload_from_checkpoint = staticmethod(payload_from_checkpoint)
    _json_safe = staticmethod(json_safe)
    _date_from_checkpoint = staticmethod(date_from_checkpoint)
    _documents_payload = staticmethod(documents_payload)
    _documents_from_payload = staticmethod(documents_from_payload)

    def _discovery_fetch_settings_from_checkpoint(self, payload: Any, checkpoint: dict) -> dict:
        settings = (
            checkpoint.get("discovery_fetch_settings")
            if isinstance(checkpoint.get("discovery_fetch_settings"), dict)
            else {}
        )
        fallback_limit_per_query, fallback_evidence_limit, fallback_max_queries = (
            self.discovery_fetch_settings_func(payload)
        )
        evidence_limit = int(settings.get("evidence_limit") or fallback_evidence_limit)
        document_limit = int(
            settings.get("document_limit")
            or self.discovery_document_limit_func(payload, evidence_limit)
        )
        return {
            "limit_per_query": int(settings.get("limit_per_query") or fallback_limit_per_query),
            "evidence_limit": evidence_limit,
            "max_queries": int(settings.get("max_queries") or fallback_max_queries),
            "document_limit": document_limit,
        }

    @staticmethod
    def _market_data_payload(market_data: dict) -> dict:
        return discovered_market_payload.market_data_payload(market_data)

    @staticmethod
    def _market_data_from_payload(payload: dict) -> dict:
        return discovered_market_payload.market_data_from_payload(payload)


__all__ = [
    "DiscoveredTopicPipelineService",
    "ReportExecutionError",
    "candidate_filing_revalidation_tickers",
    "company_filing_timeout_result",
    "should_revalidate_candidate_filings",
]
