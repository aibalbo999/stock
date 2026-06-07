from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from app.data_sources.market import MarketFetchError
from app.data_sources.company_filings import company_filing_error
from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportResponse,
    ValuationMetric,
)
from app.services.discovery_workflow import is_deep_discovery
from app.services.ingestion import (
    company_filing_attempt_result,
    company_filing_gap_summary,
    company_filing_next_actions,
    company_filing_ticker_result,
)
from app.services.report_generator import ReportExecutionError
from app.services.report_followup import matching_follow_up_rerun_report_id
from app.services.task_cancellation import TaskCancelledError, raise_if_task_cancelled
from app.services.workflow_checkpoint import WorkflowCheckpointRecorder


def should_revalidate_candidate_filings(candidates: list[dict], min_supported_ratio: float = 0.6) -> bool:
    if not candidates:
        return False
    supported = sum(1 for candidate in candidates if candidate.get("status") == "evidence_supported")
    return (supported / len(candidates)) < min_supported_ratio


def candidate_filing_revalidation_tickers(candidates: list[dict], payload: Any) -> list[str]:
    limit = 20 if is_deep_discovery(payload) else 12
    prioritized = [
        str(candidate.get("ticker"))
        for candidate in candidates
        if candidate.get("ticker") and candidate.get("status") != "evidence_supported"
    ]
    fallback = [str(candidate.get("ticker")) for candidate in candidates if candidate.get("ticker")]
    return list(dict.fromkeys([*prioritized, *fallback]))[:limit]


def company_filing_timeout_result(tickers: list[str], exc: Exception, source: str) -> dict:
    errors = [
        {
            **company_filing_error(source, exc, stage="timeout"),
            "ticker": ticker,
            "company_name": "",
        }
        for ticker in tickers
    ]
    per_ticker_results = [
        company_filing_ticker_result(
            ticker,
            "",
            [],
            ("annual_report",),
            [error],
            [company_filing_attempt_result(source, [], [error])],
        )
        for ticker, error in zip(tickers, errors)
    ]
    return {
        "requested_tickers": tickers,
        "stored_count": 0,
        "items": [],
        "errors": errors,
        "per_ticker_results": per_ticker_results,
        "missing_tickers": list(tickers),
        "gap_summary": company_filing_gap_summary(per_ticker_results),
        "next_actions": company_filing_next_actions(per_ticker_results),
        "source": f"{source} timed out",
    }


class DiscoveredTopicPipelineService:
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
            candidate_payload = self.apply_company_filing_gate_func(candidate_payload)
            source_audit["candidate_support"] = self.summarize_candidate_support_payload_func(candidate_payload)
            promoted_tickers = [
                candidate["ticker"]
                for candidate in candidate_payload
                if candidate["status"] == "evidence_supported"
            ]
            dynamic_whitelist = self.supply_chain_whitelist_cls.from_candidate_whitelist(candidate_payload)
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "candidate_count": len(candidate_payload),
                    "promoted_count": len(promoted_tickers),
                    "candidate_filing_attempted": candidate_filing_ingestion is not None,
                },
            )
            company_filing_ingestion = self._promoted_company_filing_ingestion(promoted_tickers)
            documents = self.dedupe_documents_func(
                [*documents, *self._latest_company_filing_news_documents(promoted_tickers, limit_per_ticker=4)]
            )
            self._checkpoint_stage_payload(
                run_id,
                workflow,
                {
                    "source_documents": self._documents_payload(documents),
                    "candidate_filing_ingestion": candidate_filing_ingestion,
                    "company_filing_ingestion": company_filing_ingestion,
                    "source_audit": source_audit,
                    "candidate_whitelist": candidate_payload,
                    "promoted_tickers": promoted_tickers,
                },
            )

            current_step = "market_data_refresh"
            self._check_cancelled(run_id)
            workflow.start_step(run_id, current_step, {"promoted_count": len(promoted_tickers)})
            market_data = await self._discovered_market_data_service(run_id).fetch_and_persist_for_discovery(
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
            return {
                "run_id": run_id,
                "run_record_updated": run_record_updated,
                "report_id": report_id,
                "active_report_id": active_report_id,
                "auto_follow_up": auto_follow_up,
                "discovery": discovery,
                "queries": urls,
                "fixed_source_ingestion": fixed_source_ingestion,
                "dynamic_query_ingestion": dynamic_query_ingestion,
                "candidate_filing_ingestion": candidate_filing_ingestion,
                "company_filing_ingestion": company_filing_ingestion,
                "source_audit": source_audit,
                "candidate_whitelist": candidate_payload,
                "promoted_tickers": promoted_tickers,
                "market": run_payload["market"],
                "market_history_count": run_payload["market_history_count"],
                "market_errors": run_payload["market_errors"],
                "monthly_revenue": run_payload["monthly_revenue"],
                "monthly_revenue_errors": run_payload["monthly_revenue_errors"],
                "latest_monthly_revenue": run_payload["latest_monthly_revenue"],
                "financial_metrics_count": run_payload["financial_metrics_count"],
                "financial_metric_errors": run_payload["financial_metric_errors"],
                "valuations": run_payload["valuations"],
                "valuation_errors": run_payload["valuation_errors"],
                "quality_gate": quality_gate,
                "report_execution": report_execution,
                "request": request.model_dump(mode="json"),
                "topic": request.topic,
                "report": response.model_dump(mode="json"),
            }
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
                payload = await self._resume_topic_discovery_stage(run_id, workflow_recorder, payload)
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
                payload = self._resume_candidate_revalidation_stage(run_id, workflow_recorder, payload)
            except Exception as exc:
                workflow_recorder.fail_step(run_id, "candidate_revalidation", str(exc))
                self.safe_mark_run_failed_func(run_id, str(exc))
                raise
            try:
                payload = await self._resume_market_data_refresh_stage(run_id, workflow_recorder, payload)
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
                payload = await self._resume_market_data_refresh_stage(run_id, workflow_recorder, payload)
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
            request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
            candidate_payload = payload.get("candidate_whitelist") if isinstance(payload.get("candidate_whitelist"), list) else []
            promoted_tickers = request_payload.get("tickers") or self._promoted_tickers_from_candidates(candidate_payload)
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
            return {
                "run_id": run_id,
                "run_record_updated": run_record_updated,
                "report_id": report_id,
                "active_report_id": active_report_id,
                "auto_follow_up": auto_follow_up,
                "discovery": payload.get("discovery") or {},
                "queries": payload.get("queries") or [],
                "fixed_source_ingestion": payload.get("fixed_source_ingestion") or {},
                "dynamic_query_ingestion": payload.get("dynamic_query_ingestion") or [],
                "candidate_filing_ingestion": payload.get("candidate_filing_ingestion"),
                "company_filing_ingestion": payload.get("company_filing_ingestion") or {},
                "source_audit": payload.get("source_audit") or {},
                "candidate_whitelist": candidate_payload,
                "promoted_tickers": promoted_tickers,
                "market": payload.get("market") or [],
                "market_history_count": payload.get("market_history_count", 0),
                "market_errors": payload.get("market_errors") or [],
                "monthly_revenue": payload.get("monthly_revenue") or [],
                "monthly_revenue_errors": payload.get("monthly_revenue_errors") or [],
                "latest_monthly_revenue": payload.get("latest_monthly_revenue") or [],
                "financial_metrics_count": payload.get("financial_metrics_count", 0),
                "financial_metric_errors": payload.get("financial_metric_errors") or [],
                "valuations": payload.get("valuations") or [],
                "valuation_errors": payload.get("valuation_errors") or [],
                "quality_gate": payload.get("quality_gate") or {},
                "report_execution": payload.get("report_execution") or {},
                "request": request_payload,
                "topic": request_payload.get("topic") or payload.get("topic"),
                "report": response.model_dump(mode="json"),
                "resumed_from_step": current_step,
            }
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
            payload = await self._resume_market_data_refresh_stage(run_id, workflow_recorder, payload)
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

    async def _resume_topic_discovery_stage(self, run_id: int, workflow: Any, checkpoint: dict) -> dict:
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

    async def _resume_source_ingestion_stage(self, run_id: int, workflow: Any, checkpoint: dict) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        service = self.topic_discovery_service_cls()
        discovery = checkpoint.get("discovery") if isinstance(checkpoint.get("discovery"), dict) else {}
        if not isinstance(discovery.get("plan"), dict):
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires discovery.plan")
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

    def _resume_candidate_revalidation_stage(self, run_id: int, workflow: Any, checkpoint: dict) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        service = self.topic_discovery_service_cls()
        discovery = checkpoint.get("discovery") if isinstance(checkpoint.get("discovery"), dict) else {}
        if not isinstance(discovery.get("plan"), dict):
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires discovery.plan")
        plan = self.topic_discovery_plan_cls.model_validate(discovery["plan"])
        documents = self._documents_from_payload(checkpoint.get("source_documents") or [])
        source_audit = checkpoint.get("source_audit") if isinstance(checkpoint.get("source_audit"), dict) else {}
        candidate_payload = (
            checkpoint.get("candidate_whitelist")
            if isinstance(checkpoint.get("candidate_whitelist"), list)
            else []
        )
        if not candidate_payload:
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires candidate_whitelist")
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
        candidate_payload = self.apply_company_filing_gate_func(candidate_payload)
        source_audit["candidate_support"] = self.summarize_candidate_support_payload_func(candidate_payload)
        promoted_tickers = self._promoted_tickers_from_candidates(candidate_payload)
        if not promoted_tickers:
            raise ReportExecutionError("ai_discovered_topic_pipeline resume produced no promoted_tickers")
        company_filing_ingestion = self._promoted_company_filing_ingestion(promoted_tickers)
        documents = self.dedupe_documents_func(
            [*documents, *self._latest_company_filing_news_documents(promoted_tickers, limit_per_ticker=4)]
        )
        workflow.complete_step(
            run_id,
            current_step,
            {
                "candidate_count": len(candidate_payload),
                "promoted_count": len(promoted_tickers),
                "candidate_filing_attempted": candidate_filing_ingestion is not None,
                "resumed": True,
            },
        )
        updates = {
            "source_documents": self._documents_payload(documents),
            "candidate_filing_ingestion": candidate_filing_ingestion,
            "company_filing_ingestion": company_filing_ingestion,
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
            "promoted_tickers": promoted_tickers,
        }
        self._checkpoint_stage_payload(run_id, workflow, updates)
        return {**checkpoint, **self._json_safe(updates)}

    async def _resume_market_data_refresh_stage(self, run_id: int, workflow: Any, checkpoint: dict) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        promoted_tickers = (
            checkpoint.get("promoted_tickers")
            if isinstance(checkpoint.get("promoted_tickers"), list)
            else []
        )
        if not promoted_tickers:
            promoted_tickers = self._promoted_tickers_from_candidates(
                checkpoint.get("candidate_whitelist") if isinstance(checkpoint.get("candidate_whitelist"), list) else []
            )
        if not promoted_tickers:
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires promoted_tickers")
        end_date = self._date_from_checkpoint(checkpoint.get("discovery_end_date"))
        current_step = "market_data_refresh"
        workflow.start_step(
            run_id,
            current_step,
            {"promoted_count": len(promoted_tickers), "resumed": True},
        )
        market_data = await self._discovered_market_data_service(run_id).fetch_and_persist_for_discovery(
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

    async def _resume_report_build(
        self,
        run_id: int,
        workflow: Any,
        checkpoint: dict,
        *,
        resume_origin: str = "report_build",
    ) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        discovery = checkpoint.get("discovery") if isinstance(checkpoint.get("discovery"), dict) else {}
        settings = (
            checkpoint.get("discovery_fetch_settings")
            if isinstance(checkpoint.get("discovery_fetch_settings"), dict)
            else {}
        )
        evidence_limit = int(settings.get("evidence_limit") or getattr(payload, "evidence_limit", 40))
        urls = checkpoint.get("queries") if isinstance(checkpoint.get("queries"), list) else []
        documents = self._documents_from_payload(checkpoint.get("source_documents") or [])
        source_audit = checkpoint.get("source_audit") if isinstance(checkpoint.get("source_audit"), dict) else {}
        candidate_payload = (
            checkpoint.get("candidate_whitelist")
            if isinstance(checkpoint.get("candidate_whitelist"), list)
            else []
        )
        promoted_tickers = (
            checkpoint.get("promoted_tickers")
            if isinstance(checkpoint.get("promoted_tickers"), list)
            else []
        )
        if not promoted_tickers:
            promoted_tickers = self._promoted_tickers_from_candidates(candidate_payload)
        if not promoted_tickers:
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires promoted_tickers")
        market_payload = checkpoint.get("market_data") if isinstance(checkpoint.get("market_data"), dict) else {}
        market_data = self._market_data_from_payload(market_payload)
        if not market_data.get("snapshots") and not market_data.get("latest_monthly_revenues"):
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires checkpointed market_data")
        dynamic_whitelist = self.supply_chain_whitelist_cls.from_candidate_whitelist(candidate_payload)

        current_step = "report_build"
        workflow.start_step(
            run_id,
            current_step,
            {"promoted_count": len(promoted_tickers), "resumed": True},
        )
        report_result = self.discovered_report_builder_service_factory().build_and_store_report(
            payload=payload,
            promoted_tickers=promoted_tickers,
            dynamic_whitelist=dynamic_whitelist,
            documents=documents,
            evidence_limit=evidence_limit,
            source_audit=source_audit,
            discovery=discovery,
            urls=urls,
            ingestion_results=checkpoint.get("ingestion") or [],
            fixed_source_ingestion=checkpoint.get("fixed_source_ingestion") or {},
            dynamic_query_ingestion=checkpoint.get("dynamic_query_ingestion") or [],
            candidate_filing_ingestion=checkpoint.get("candidate_filing_ingestion"),
            company_filing_ingestion=checkpoint.get("company_filing_ingestion") or {},
            candidate_payload=candidate_payload,
            market_data=market_data,
            run_id=run_id,
        )
        response = report_result["response"]
        request = report_result.get("request") or payload
        report_id = report_result["report_id"]
        quality_gate = report_result["quality_gate"]
        report_execution = report_result["report_execution"]
        run_payload = {
            **report_result["run_payload"],
            "report_id": report_id,
            "resumed_from_step": resume_origin,
        }
        workflow.complete_step(
            run_id,
            current_step,
            {
                "report_id": report_id,
                "quality_gate_status": quality_gate.get("status"),
                "evidence_count": report_execution.get("evidence_count"),
                "resumed": True,
            },
        )
        self._checkpoint_report_build_payload(run_id, workflow, run_payload)
        current_step = "auto_follow_up"
        workflow.start_step(run_id, current_step, {"report_id": report_id, "resumed": True})
        run_payload = workflow.complete_workflow_payload(run_id, run_payload)
        run_record_updated = self.safe_update_run_success_func(run_id, run_payload, report_id)
        auto_follow_up = await self.auto_follow_up_func(report_id)
        active_report_id = (
            matching_follow_up_rerun_report_id(
                auto_follow_up,
                report_id,
                source_topic=getattr(request, "topic", None),
                source_tickers=getattr(request, "tickers", None) or promoted_tickers,
            )
            or report_id
        )
        workflow.complete_step(
            run_id,
            current_step,
            {
                "status": auto_follow_up.get("status"),
                "rerun_report_id": active_report_id if active_report_id != report_id else None,
                "resumed": True,
            },
        )
        request_payload = (
            request.model_dump(mode="json")
            if hasattr(request, "model_dump")
            else self._payload_model_dump(request)
        )
        return {
            "run_id": run_id,
            "run_record_updated": run_record_updated,
            "report_id": report_id,
            "active_report_id": active_report_id,
            "auto_follow_up": auto_follow_up,
            "discovery": discovery,
            "queries": urls,
            "fixed_source_ingestion": checkpoint.get("fixed_source_ingestion") or {},
            "dynamic_query_ingestion": checkpoint.get("dynamic_query_ingestion") or [],
            "candidate_filing_ingestion": checkpoint.get("candidate_filing_ingestion"),
            "company_filing_ingestion": checkpoint.get("company_filing_ingestion") or {},
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
            "promoted_tickers": promoted_tickers,
            "market": run_payload["market"],
            "market_history_count": run_payload["market_history_count"],
            "market_errors": run_payload["market_errors"],
            "monthly_revenue": run_payload["monthly_revenue"],
            "monthly_revenue_errors": run_payload["monthly_revenue_errors"],
            "latest_monthly_revenue": run_payload["latest_monthly_revenue"],
            "financial_metrics_count": run_payload["financial_metrics_count"],
            "financial_metric_errors": run_payload["financial_metric_errors"],
            "valuations": run_payload["valuations"],
            "valuation_errors": run_payload["valuation_errors"],
            "quality_gate": quality_gate,
            "report_execution": report_execution,
            "request": request_payload,
            "topic": request_payload.get("topic"),
            "report": response.model_dump(mode="json"),
            "resumed_from_step": resume_origin,
        }

    def _start_run(self, payload: Any) -> int:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).start(
                "pipeline_ai_discovery",
                payload.model_dump(mode="json"),
            )
            return run.id

    def _checkpoint_stage_payload(self, run_id: int, workflow: Any, updates: dict) -> bool:
        current_payload = self._current_run_payload(run_id)
        payload = {**current_payload, **self._json_safe(updates)}
        return self._update_run_payload(
            run_id,
            workflow.payload_with_current_workflow(run_id, payload),
        )

    def _checkpoint_report_build_payload(self, run_id: int, workflow: Any, run_payload: dict) -> bool:
        payload = workflow.payload_with_current_workflow(run_id, run_payload)
        return self._update_run_payload(run_id, payload)

    def _attach_celery_task_id(self, run_id: int, celery_task_id: str) -> bool:
        current_payload = self._current_run_payload(run_id)
        return self._update_run_payload(run_id, {**current_payload, "celery_task_id": celery_task_id})

    def _update_run_payload(self, run_id: int, payload: dict) -> bool:
        try:
            with self.session_scope_factory() as session:
                repository = self.analysis_run_repository_cls(session)
                if not hasattr(repository, "update_payload") or repository.get(run_id) is None:
                    return False
                repository.update_payload(run_id, payload)
                return True
        except Exception:
            return False

    def _current_run_payload(self, run_id: int) -> dict:
        try:
            with self.session_scope_factory() as session:
                run = self.analysis_run_repository_cls(session).get(run_id)
            return self._parse_payload(getattr(run, "payload_json", None)) if run is not None else {}
        except Exception:
            return {}

    def _mark_run_running(self, run_id: int) -> None:
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            if hasattr(repository, "mark_running"):
                repository.mark_running(run_id)

    def _mark_run_cancelled(self, run_id: int, reason: str) -> None:
        with self.session_scope_factory() as session:
            repository = self.analysis_run_repository_cls(session)
            mark_cancelled = getattr(repository, "mark_cancelled", None)
            if callable(mark_cancelled):
                mark_cancelled(run_id, reason)
            else:
                self.safe_mark_run_failed_func(run_id, reason)

    def _check_cancelled(self, run_id: int) -> None:
        if self.task_cancellation_checker is not None:
            self.task_cancellation_checker(run_id)
            return
        raise_if_task_cancelled(
            run_id,
            session_scope_factory=self.session_scope_factory,
            analysis_run_repository_cls=self.analysis_run_repository_cls,
        )

    def _discovered_market_data_service(self, run_id: int) -> Any:
        try:
            return self.discovered_market_data_service_factory(
                cancellation_checker=lambda: self._check_cancelled(run_id)
            )
        except TypeError:
            service = self.discovered_market_data_service_factory()
            if hasattr(service, "cancellation_checker"):
                service.cancellation_checker = lambda: self._check_cancelled(run_id)
            return service

    def _load_resumable_discovered_run(self, run_id: int) -> tuple[Any, dict, dict]:
        with self.session_scope_factory() as session:
            run = self.analysis_run_repository_cls(session).get(run_id)
        if run is None:
            raise ReportExecutionError(f"analysis run not found: {run_id}")
        payload = self._parse_payload(getattr(run, "payload_json", None))
        workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else None
        if not workflow or workflow.get("name") != "ai_discovered_topic_pipeline":
            raise ReportExecutionError("run is not a resumable ai_discovered_topic_pipeline workflow")
        resume = (
            workflow.get("resume")
            if isinstance(workflow.get("resume"), dict)
            else WorkflowCheckpointRecorder.resume_state(workflow)
        )
        if not resume.get("resumable"):
            raise ReportExecutionError("ai_discovered_topic_pipeline workflow is not resumable")
        return run, payload, workflow

    @staticmethod
    def _parse_payload(payload_json: str | None) -> dict:
        if not payload_json:
            return {}
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _resume_report_id(run: Any, payload: dict) -> int:
        value = getattr(run, "report_id", None) or payload.get("report_id")
        try:
            report_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires an existing report_id") from exc
        if report_id <= 0:
            raise ReportExecutionError("ai_discovered_topic_pipeline resume requires an existing report_id")
        return report_id

    @staticmethod
    def _promoted_tickers_from_candidates(candidates: list[dict]) -> list[str]:
        return [
            str(candidate.get("ticker"))
            for candidate in candidates
            if candidate.get("ticker") and candidate.get("status") == "evidence_supported"
        ]

    def _load_report_response(self, report_id: int) -> ReportResponse:
        with self.session_scope_factory() as session:
            report = self.report_repository_cls(session).get(report_id)
        if report is None:
            raise ReportExecutionError(f"report not found for resume: {report_id}")
        return ReportResponse(title=report.title, markdown=report.markdown)

    @staticmethod
    def _payload_model_dump(payload: Any) -> dict:
        dump = getattr(payload, "model_dump", None)
        if callable(dump):
            try:
                return dump(mode="json")
            except TypeError:
                return dump()
        if isinstance(payload, dict):
            return dict(payload)
        return {
            key: value
            for key, value in vars(payload).items()
            if not key.startswith("_") and not callable(value)
        }

    @classmethod
    def _payload_from_checkpoint(cls, checkpoint: dict) -> Any:
        raw = checkpoint.get("pipeline_request")
        if not isinstance(raw, dict):
            raw = checkpoint.get("request") if isinstance(checkpoint.get("request"), dict) else {}
        if not raw:
            request_keys = {
                "topic",
                "limit_per_query",
                "lookback_days",
                "evidence_limit",
                "analysis_mode",
                "deep_analysis",
                "include_international",
                "investor_capital",
                "beginner_mode",
                "investor_profile",
                "max_position_pct",
                "cash_reserve_pct",
            }
            raw = {key: checkpoint[key] for key in request_keys if key in checkpoint}
        defaults = {
            "topic": "AI 產業鏈",
            "limit_per_query": 5,
            "lookback_days": 14,
            "evidence_limit": 40,
            "analysis_mode": "standard",
            "deep_analysis": False,
            "include_international": True,
            "investor_capital": 1_000_000,
            "beginner_mode": True,
            "investor_profile": "beginner",
            "max_position_pct": 0.10,
            "cash_reserve_pct": 0.30,
        }
        values = {**defaults, **raw}

        class PayloadAdapter:
            def __init__(self, data: dict) -> None:
                self.__dict__.update(data)

            def model_dump(self, mode=None):
                return dict(self.__dict__)

        return PayloadAdapter(values)

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
            settings.get("document_limit") or self.discovery_document_limit_func(payload, evidence_limit)
        )
        return {
            "limit_per_query": int(settings.get("limit_per_query") or fallback_limit_per_query),
            "evidence_limit": evidence_limit,
            "max_queries": int(settings.get("max_queries") or fallback_max_queries),
            "document_limit": document_limit,
        }

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            try:
                return dump(mode="json")
            except TypeError:
                return dump()
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    @staticmethod
    def _date_from_checkpoint(value: Any) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise ReportExecutionError(
                    "ai_discovered_topic_pipeline resume requires valid discovery_end_date"
                ) from exc
        raise ReportExecutionError("ai_discovered_topic_pipeline resume requires discovery_end_date")

    @classmethod
    def _documents_payload(cls, documents: list) -> list:
        return [cls._json_safe(document) for document in documents]

    @staticmethod
    def _documents_from_payload(documents: list) -> list:
        restored = []
        for document in documents:
            if isinstance(document, dict) and {"id", "title", "text", "source"}.issubset(document):
                restored.append(NewsDocument.model_validate(document))
            else:
                restored.append(document)
        return restored

    @classmethod
    def _market_data_payload(cls, market_data: dict) -> dict:
        return {
            "snapshots": cls._json_safe(market_data.get("snapshots") or []),
            "price_history_snapshots": cls._json_safe(market_data.get("price_history_snapshots") or []),
            "market_errors": cls._json_safe(market_data.get("market_errors") or []),
            "monthly_revenues": cls._json_safe(market_data.get("monthly_revenues") or []),
            "monthly_revenue_errors": cls._json_safe(market_data.get("monthly_revenue_errors") or []),
            "latest_monthly_revenues": cls._json_safe(market_data.get("latest_monthly_revenues") or []),
            "financial_metrics": cls._json_safe(market_data.get("financial_metrics") or []),
            "financial_metric_errors": cls._json_safe(market_data.get("financial_metric_errors") or []),
            "valuations": cls._json_safe(market_data.get("valuations") or []),
            "valuation_errors": cls._json_safe(market_data.get("valuation_errors") or []),
        }

    @staticmethod
    def _market_data_from_payload(payload: dict) -> dict:
        return {
            "snapshots": [MarketSnapshot.model_validate(item) for item in payload.get("snapshots") or []],
            "price_history_snapshots": [
                MarketSnapshot.model_validate(item) for item in payload.get("price_history_snapshots") or []
            ],
            "market_errors": [MarketFetchError(**item) for item in payload.get("market_errors") or []],
            "monthly_revenues": [
                MonthlyRevenue.model_validate(item) for item in payload.get("monthly_revenues") or []
            ],
            "monthly_revenue_errors": [
                MarketFetchError(**item) for item in payload.get("monthly_revenue_errors") or []
            ],
            "latest_monthly_revenues": [
                MonthlyRevenue.model_validate(item) for item in payload.get("latest_monthly_revenues") or []
            ],
            "financial_metrics": [
                FinancialMetric.model_validate(item) for item in payload.get("financial_metrics") or []
            ],
            "financial_metric_errors": [
                MarketFetchError(**item) for item in payload.get("financial_metric_errors") or []
            ],
            "valuations": [ValuationMetric.model_validate(item) for item in payload.get("valuations") or []],
            "valuation_errors": [
                MarketFetchError(**item) for item in payload.get("valuation_errors") or []
            ],
        }

    def _revalidate_candidates(
        self,
        payload: Any,
        service: Any,
        plan: Any,
        source_audit: dict,
        candidate_payload: list[dict],
        documents: list,
    ) -> tuple[dict | None, list[dict], list]:
        candidate_filing_ingestion = None
        if not self.should_revalidate_candidate_filings_func(candidate_payload):
            return candidate_filing_ingestion, candidate_payload, documents
        candidate_tickers = self.candidate_filing_revalidation_tickers_func(candidate_payload, payload)
        candidate_filing_ingestion = self.company_filing_timeout_result_func(
            candidate_tickers,
            RuntimeError("skipped during synchronous deep analysis; queued as follow-up"),
            "candidate MOPS annual report discovery",
        )
        candidate_filing_documents = self._latest_company_filing_news_documents(
            candidate_tickers,
            limit_per_ticker=2,
        )
        if not candidate_filing_documents:
            return candidate_filing_ingestion, candidate_payload, documents

        documents = self.dedupe_documents_func([*documents, *candidate_filing_documents])
        revalidated_candidates = service.validate_candidates(plan, documents)
        candidate_payload = [candidate.model_dump() for candidate in revalidated_candidates]
        source_audit["candidate_support"] = self.summarize_candidate_support_func(revalidated_candidates)
        source_audit["candidate_filing_revalidation"] = {
            "attempted": True,
            "stored_count": candidate_filing_ingestion.get("stored_count", 0),
            "document_count": len(candidate_filing_documents),
            "promoted_after_revalidation": [
                candidate["ticker"]
                for candidate in candidate_payload
                if candidate["status"] == "evidence_supported"
            ],
            "requested_tickers": candidate_tickers,
        }
        return candidate_filing_ingestion, candidate_payload, documents

    def _promoted_company_filing_ingestion(self, promoted_tickers: list[str]) -> dict:
        if promoted_tickers:
            return self.company_filing_timeout_result_func(
                promoted_tickers,
                RuntimeError("skipped during synchronous deep analysis; queued as follow-up"),
                "promoted MOPS annual report discovery",
            )
        return {
            "requested_tickers": [],
            "stored_count": 0,
            "per_ticker_results": [],
            "gap_summary": {"blocked_tickers": [], "retryable_tickers": []},
            "errors": [],
            "source": "Company filing discovery skipped: no promoted candidates",
        }

    def _latest_company_filing_news_documents(
        self,
        tickers: list[str],
        *,
        limit_per_ticker: int,
    ) -> list:
        with self.session_scope_factory() as session:
            return [
                self.company_filing_repository_cls.to_news_document(document)
                for document in self.company_filing_repository_cls(session).latest_by_tickers(
                    tickers,
                    limit_per_ticker=limit_per_ticker,
                )
            ]


__all__ = [
    "DiscoveredTopicPipelineService",
    "ReportExecutionError",
    "candidate_filing_revalidation_tickers",
    "company_filing_timeout_result",
    "should_revalidate_candidate_filings",
]
