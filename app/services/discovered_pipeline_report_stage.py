from __future__ import annotations

from typing import Any

from app.services.discovered_pipeline_results import discovered_pipeline_result_payload
from app.services.report_generator import ReportExecutionError
from app.services.report_followup import matching_follow_up_rerun_report_id


class DiscoveredPipelineReportStageMixin:
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


__all__ = ["DiscoveredPipelineReportStageMixin"]
