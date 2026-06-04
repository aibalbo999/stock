from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.models.schemas import ReportRequest
from app.services.report_followup_context import ReportFollowUpContextNotFound
from app.services.report_generator import ReportExecutionError
from app.services.workflow_orchestration import WorkflowOrchestrationError


class ApiCompatibilityService:
    """Compatibility boundary for legacy app.api.main helper imports.

    FastAPI routers call use-case services directly. A few tests, scripts, and
    factory hooks still import historical helper functions from app.api.main, so
    this service keeps that delegation outside the API entry module.
    """

    def __init__(
        self,
        *,
        api_services: Any,
        candidate_revalidation_module: Any,
        follow_up_run_request_cls: Callable[[], Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.api_services = api_services
        self.candidate_revalidation_module = candidate_revalidation_module
        self.follow_up_run_request_cls = follow_up_run_request_cls
        self.logger = logger or logging.getLogger(__name__)

    def sufficient_company_filing_tickers(self, tickers: list[str]) -> set[str]:
        return self.api_services.candidate_revalidation().sufficient_company_filing_tickers(tickers)

    def count_sufficient_company_filings(self, tickers: list[str]) -> int:
        return len(self.sufficient_company_filing_tickers(tickers))

    def apply_company_filing_gate_to_candidate_payload(
        self,
        candidates: list[dict],
        *,
        sufficient_tickers_provider: Any | None = None,
    ) -> list[dict]:
        return self.candidate_revalidation_module.apply_company_filing_gate_to_candidate_payload(
            candidates,
            sufficient_tickers_provider=sufficient_tickers_provider
            or self.sufficient_company_filing_tickers,
        )

    def safe_mark_run_failed(self, run_id: int, error: str) -> None:
        return self.api_services.run_state().safe_mark_failed(run_id, error)

    def safe_update_run_success(self, run_id: int, payload: dict, report_id: int) -> bool:
        return self.api_services.run_state().safe_update_success(run_id, payload, report_id)

    def load_report_follow_up_context(self, report_id: int) -> dict:
        try:
            return self.api_services.report_follow_up_context().load(report_id)
        except ReportFollowUpContextNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def revalidate_candidate_whitelist(
        self,
        run_payload: dict,
        fallback_candidates: list[dict],
        limit: int = 500,
    ) -> dict:
        return self.api_services.candidate_revalidation().revalidate_candidate_whitelist(
            run_payload,
            fallback_candidates,
            limit,
        )

    def preserve_previous_supported_candidates(
        self,
        current_candidates: list[dict],
        previous_candidates: list[dict],
    ) -> list[dict]:
        return self.candidate_revalidation_module.preserve_previous_supported_candidates(
            current_candidates,
            previous_candidates,
        )

    def mark_unavailable_candidates_after_revalidation(
        self,
        candidates: list[dict],
        document_count: int,
    ) -> list[dict]:
        return self.candidate_revalidation_module.mark_unavailable_candidates_after_revalidation(
            candidates,
            document_count,
        )

    def candidate_revalidation_queries(
        self,
        plan: Any,
        topic: str = "",
        limit: int = 80,
    ) -> list[str]:
        return self.candidate_revalidation_module.candidate_revalidation_queries(plan, topic, limit)

    def collect_revalidation_documents(self, repository: Any, queries: list[str], limit: int) -> list:
        return self.candidate_revalidation_module.collect_revalidation_documents(
            repository,
            queries,
            limit,
        )

    def dedupe_documents(self, documents: list) -> list:
        return self.candidate_revalidation_module.dedupe_documents(documents)

    def persist_candidate_entity_matches(
        self,
        plan: Any,
        candidates: list,
        documents: list,
    ) -> dict:
        return self.api_services.candidate_revalidation().persist_candidate_entity_matches(
            plan,
            candidates,
            documents,
        )

    def dedupe_strings(self, values: list[str], limit: int) -> list[str]:
        return self.candidate_revalidation_module.dedupe_strings(values, limit)

    async def prepare_follow_up_report_context(
        self,
        context: dict,
        request: ReportRequest,
        actions: list,
    ) -> dict:
        return await self.api_services.report_follow_up_context().prepare(context, request, actions)

    async def refresh_market_data_for_report(self, request: ReportRequest) -> dict:
        return await self.api_services.report_follow_up_context().refresh_market_data(request)

    async def ingest_dynamic_news_urls(
        self,
        urls: list[str],
        limit_per_query: int,
        start_date,
        end_date,
    ) -> list[dict]:
        return await self.api_services.discovery_workflow().ingest_dynamic_news_urls(
            urls,
            limit_per_query,
            start_date,
            end_date,
        )

    async def run_topic_discovery_ingestion(
        self,
        payload: Any,
        service: Any,
        plan: Any,
        limit_per_query: int,
        evidence_limit: int,
        max_queries: int,
        document_limit: int,
    ) -> dict:
        return await self.api_services.discovery_workflow().run_topic_discovery_ingestion(
            payload,
            service,
            plan,
            limit_per_query,
            evidence_limit,
            max_queries,
            document_limit,
        )

    async def discover_topic_with_timeout(self, service: Any, topic: str, timeout: int = 75) -> dict:
        return await self.api_services.discovery_workflow().discover_topic_with_timeout(
            service,
            topic,
            timeout,
        )

    def get_report_follow_up_plan(self, report_id: int) -> dict:
        return self.api_services.report_follow_up_plan().build(report_id)

    async def maybe_auto_start_required_follow_up(
        self,
        report_id: int,
        run_in_background: bool = True,
    ) -> dict:
        return await self.api_services.auto_follow_up_start().start(report_id, run_in_background)

    async def run_required_follow_up_background(
        self,
        report_id: int,
        payload: Any,
    ) -> None:
        try:
            await self.run_report_follow_up(report_id, payload)
        except Exception:
            self.logger.exception("auto follow-up failed for report %s", report_id)

    async def run_report_follow_up(
        self,
        report_id: int,
        payload: Any | None = None,
    ) -> dict:
        payload = payload or self._default_follow_up_run_request()
        try:
            return await self.api_services.report_follow_up_run().run(report_id, payload)
        except HTTPException:
            raise
        except ReportExecutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WorkflowOrchestrationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _default_follow_up_run_request(self) -> Any:
        if self.follow_up_run_request_cls is None:
            raise RuntimeError("follow_up_run_request_cls is required when payload is omitted")
        return self.follow_up_run_request_cls()
