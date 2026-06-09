from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.discovered_pipeline_results import discovered_pipeline_result_payload
from app.services.report_generator import ReportExecutionError
from app.services.report_followup import matching_follow_up_rerun_report_id


@dataclass(frozen=True)
class DiscoveredReportStageInput:
    run_id: int
    payload: Any
    promoted_tickers: list[str]
    dynamic_whitelist: Any
    documents: list[Any]
    evidence_limit: int
    source_audit: dict
    discovery: dict
    urls: list
    ingestion_results: list
    fixed_source_ingestion: dict
    dynamic_query_ingestion: list
    candidate_filing_ingestion: dict | None
    company_filing_ingestion: dict
    candidate_payload: list[dict]
    market_data: dict


@dataclass(frozen=True)
class DiscoveredReportStageResult:
    response: Any
    request: Any
    report_id: int
    quality_gate: dict
    report_execution: dict
    run_payload: dict

    def workflow_summary(self) -> dict:
        return {
            "report_id": self.report_id,
            "quality_gate_status": self.quality_gate.get("status"),
            "evidence_count": self.report_execution.get("evidence_count"),
        }


@dataclass(frozen=True)
class DiscoveredAutoFollowUpInput:
    run_id: int
    workflow: Any
    pipeline_payload: Any
    report_stage: DiscoveredReportStageResult
    discovery: dict
    queries: list
    fixed_source_ingestion: dict
    dynamic_query_ingestion: list
    candidate_filing_ingestion: dict | None
    company_filing_ingestion: dict
    source_audit: dict
    candidate_payload: list[dict]
    promoted_tickers: list[str]


class DiscoveredPipelineReportStageMixin:
    def _build_report_stage(
        self,
        stage: DiscoveredReportStageInput,
    ) -> DiscoveredReportStageResult:
        report_result = self.discovered_report_builder_service_factory().build_and_store_report(
            payload=stage.payload,
            promoted_tickers=stage.promoted_tickers,
            dynamic_whitelist=stage.dynamic_whitelist,
            documents=stage.documents,
            evidence_limit=stage.evidence_limit,
            source_audit=stage.source_audit,
            discovery=stage.discovery,
            urls=stage.urls,
            ingestion_results=stage.ingestion_results,
            fixed_source_ingestion=stage.fixed_source_ingestion,
            dynamic_query_ingestion=stage.dynamic_query_ingestion,
            candidate_filing_ingestion=stage.candidate_filing_ingestion,
            company_filing_ingestion=stage.company_filing_ingestion,
            candidate_payload=stage.candidate_payload,
            market_data=stage.market_data,
            run_id=stage.run_id,
        )
        report_id = report_result["report_id"]
        return DiscoveredReportStageResult(
            response=report_result["response"],
            request=report_result.get("request") or stage.payload,
            report_id=report_id,
            quality_gate=report_result["quality_gate"],
            report_execution=report_result["report_execution"],
            run_payload={**report_result["run_payload"], "report_id": report_id},
        )

    async def _complete_report_auto_follow_up_stage(
        self,
        stage: DiscoveredAutoFollowUpInput,
    ) -> dict:
        report_stage = stage.report_stage
        run_payload = stage.workflow.complete_workflow_payload(
            stage.run_id,
            report_stage.run_payload,
        )
        run_record_updated = self.safe_update_run_success_func(
            stage.run_id,
            run_payload,
            report_stage.report_id,
        )
        auto_follow_up = await self.auto_follow_up_func(report_stage.report_id)
        self._check_cancelled(stage.run_id)
        active_report_id = (
            matching_follow_up_rerun_report_id(
                auto_follow_up,
                report_stage.report_id,
                source_topic=stage.pipeline_payload.topic,
                source_tickers=stage.promoted_tickers,
            )
            or report_stage.report_id
        )
        stage.workflow.complete_step(
            stage.run_id,
            "auto_follow_up",
            {
                "status": auto_follow_up.get("status"),
                "rerun_report_id": (
                    active_report_id if active_report_id != report_stage.report_id else None
                ),
            },
        )
        return discovered_pipeline_result_payload(
            run_id=stage.run_id,
            run_record_updated=run_record_updated,
            report_id=report_stage.report_id,
            active_report_id=active_report_id,
            auto_follow_up=auto_follow_up,
            discovery=stage.discovery,
            queries=stage.queries,
            fixed_source_ingestion=stage.fixed_source_ingestion,
            dynamic_query_ingestion=stage.dynamic_query_ingestion,
            candidate_filing_ingestion=stage.candidate_filing_ingestion,
            company_filing_ingestion=stage.company_filing_ingestion,
            source_audit=stage.source_audit,
            candidate_whitelist=stage.candidate_payload,
            promoted_tickers=stage.promoted_tickers,
            run_payload=run_payload,
            quality_gate=report_stage.quality_gate,
            report_execution=report_stage.report_execution,
            request=report_stage.request.model_dump(mode="json"),
            topic=report_stage.request.topic,
            report=report_stage.response.model_dump(mode="json"),
        )

    async def _resume_report_build(
        self,
        run_id: int,
        workflow: Any,
        checkpoint: dict,
        *,
        resume_origin: str = "report_build",
    ) -> dict:
        payload = self._payload_from_checkpoint(checkpoint)
        discovery = (
            checkpoint.get("discovery") if isinstance(checkpoint.get("discovery"), dict) else {}
        )
        settings = (
            checkpoint.get("discovery_fetch_settings")
            if isinstance(checkpoint.get("discovery_fetch_settings"), dict)
            else {}
        )
        evidence_limit = int(
            settings.get("evidence_limit") or getattr(payload, "evidence_limit", 40)
        )
        urls = checkpoint.get("queries") if isinstance(checkpoint.get("queries"), list) else []
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
        promoted_tickers = (
            checkpoint.get("promoted_tickers")
            if isinstance(checkpoint.get("promoted_tickers"), list)
            else []
        )
        if not promoted_tickers:
            promoted_tickers = self._promoted_tickers_from_candidates(candidate_payload)
        if not promoted_tickers:
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume requires promoted_tickers"
            )
        market_payload = (
            checkpoint.get("market_data") if isinstance(checkpoint.get("market_data"), dict) else {}
        )
        market_data = self._market_data_from_payload(market_payload)
        if not market_data.get("snapshots") and not market_data.get("latest_monthly_revenues"):
            raise ReportExecutionError(
                "ai_discovered_topic_pipeline resume requires checkpointed market_data"
            )
        dynamic_whitelist = self.supply_chain_whitelist_cls.from_candidate_whitelist(
            candidate_payload
        )

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
        return discovered_pipeline_result_payload(
            run_id=run_id,
            run_record_updated=run_record_updated,
            report_id=report_id,
            active_report_id=active_report_id,
            auto_follow_up=auto_follow_up,
            discovery=discovery,
            queries=urls,
            fixed_source_ingestion=checkpoint.get("fixed_source_ingestion") or {},
            dynamic_query_ingestion=checkpoint.get("dynamic_query_ingestion") or [],
            candidate_filing_ingestion=checkpoint.get("candidate_filing_ingestion"),
            company_filing_ingestion=checkpoint.get("company_filing_ingestion") or {},
            source_audit=source_audit,
            candidate_whitelist=candidate_payload,
            promoted_tickers=promoted_tickers,
            run_payload=run_payload,
            quality_gate=quality_gate,
            report_execution=report_execution,
            request=request_payload,
            topic=request_payload.get("topic"),
            report=response.model_dump(mode="json"),
            resumed_from_step=resume_origin,
        )


__all__ = [
    "DiscoveredAutoFollowUpInput",
    "DiscoveredPipelineReportStageMixin",
    "DiscoveredReportStageInput",
    "DiscoveredReportStageResult",
]
