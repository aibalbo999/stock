from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from app.core.time import today_taipei
from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.company_data_audit import audit_company_data
from app.services.followup_actions import FollowUpAction
from app.services.ingestion import IngestionPipeline
from app.services.analysis_run_repository import AnalysisRunRepository
from app.services.persistence import ReportRepository
from app.services.report_followup import (
    append_candidate_audit_if_missing,
    candidate_audit_from_run_payload,
    datetime_iso_or_none,
    parse_run_payload,
    request_from_report_record,
)
from app.services.report_quality import parse_quality_gate_from_markdown
from app.services.whitelist import SupplyChainWhitelist


class ReportFollowUpContextNotFound(LookupError):
    pass


class ReportFollowUpContextService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable = session_scope,
        report_repository_cls=ReportRepository,
        analysis_run_repository_cls=AnalysisRunRepository,
        audit_company_data_func: Callable = audit_company_data,
        parse_quality_gate_func: Callable[[str], dict] = parse_quality_gate_from_markdown,
        candidate_revalidation_service: CandidateRevalidationService | None = None,
        supply_chain_whitelist_cls=SupplyChainWhitelist,
        ingestion_pipeline_cls=IngestionPipeline,
        today_func: Callable = today_taipei,
        revalidate_candidate_whitelist_func: Callable[[dict, list[dict]], dict] | None = None,
        refresh_market_data_func: Callable[[ReportRequest], Awaitable[dict]] | None = None,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.report_repository_cls = report_repository_cls
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.audit_company_data_func = audit_company_data_func
        self.parse_quality_gate_func = parse_quality_gate_func
        self.candidate_revalidation_service = (
            candidate_revalidation_service
            or CandidateRevalidationService(session_scope_factory=session_scope_factory)
        )
        self.supply_chain_whitelist_cls = supply_chain_whitelist_cls
        self.ingestion_pipeline_cls = ingestion_pipeline_cls
        self.today_func = today_func
        self.revalidate_candidate_whitelist_func = (
            revalidate_candidate_whitelist_func
            or self.candidate_revalidation_service.revalidate_candidate_whitelist
        )
        self.refresh_market_data_func = refresh_market_data_func or self.refresh_market_data

    def load(self, report_id: int) -> dict:
        with self.session_scope_factory() as session:
            report = self.report_repository_cls(session).get(report_id)
            if report is None:
                raise ReportFollowUpContextNotFound("report not found")
            run = self.analysis_run_repository_cls(session).get_by_report_id(report_id)
            run_payload_json = run.payload_json if run is not None else None
            tickers = self._report_tickers(report)
            markdown = report.markdown
            topic = report.topic
            run_payload = parse_run_payload(run_payload_json)
            quality_gate = self.parse_quality_gate_func(markdown) or {}
            company_data_audit = (
                self.audit_company_data_func(
                    session,
                    tickers,
                    markdown=markdown,
                    run_payload=run_payload,
                )
                if tickers and (quality_gate or run_payload)
                else {}
            )
        request = request_from_report_record(topic, tickers, run_payload_json)
        candidates = candidate_audit_from_run_payload(run_payload)
        markdown = append_candidate_audit_if_missing(markdown, candidates, request.tickers)
        return {
            "source_report_id": report_id,
            "source_report_topic": topic,
            "source_report_tickers": tickers,
            "source_report_generated_at": datetime_iso_or_none(
                getattr(report, "generated_at", None)
            ),
            "source_report_created_at": datetime_iso_or_none(getattr(report, "created_at", None)),
            "request": request,
            "markdown": markdown,
            "quality_gate": quality_gate,
            "candidate_whitelist": candidates,
            "company_data_audit": company_data_audit,
            "source_audit": run_payload.get("source_audit") or {},
            "run_payload": run_payload,
        }

    async def prepare(
        self,
        context: dict,
        request: ReportRequest,
        actions: list[FollowUpAction],
    ) -> dict:
        candidates = context.get("candidate_whitelist") or []
        should_revalidate = bool(candidates) and any(
            action.action_type in {"ingest_news", "rerun_discovery"}
            and action.purpose == "required"
            for action in actions
        )
        if should_revalidate:
            revalidation = self.revalidate_candidate_whitelist_func(
                context.get("run_payload") or {},
                candidates,
            )
            if not revalidation["promoted_tickers"] and request.tickers:
                candidate_payload = candidates
                promoted_tickers = request.tickers
                revalidation = {
                    **revalidation,
                    "candidate_whitelist": candidates,
                    "promoted_tickers": request.tickers,
                    "changed": False,
                    "status_changes": [],
                    "no_longer_promoted": [],
                    "revalidation_status": "kept_previous_promotions",
                    "revalidation_reason": "本次補強資料未能穩定重建候選證據，保留上一版正式分析清單並由資料品質門檻控管。",
                }
            else:
                candidate_payload = revalidation["candidate_whitelist"] or candidates
                promoted_tickers = revalidation["promoted_tickers"] or request.tickers
        else:
            revalidation = {
                "candidate_whitelist": candidates,
                "promoted_tickers": request.tickers,
                "newly_promoted": [],
                "no_longer_promoted": [],
                "status_changes": [],
                "changed": False,
            }
            candidate_payload = candidates
            promoted_tickers = request.tickers

        rerun_request = request.model_copy(update={"tickers": promoted_tickers})
        if revalidation.get("changed") and promoted_tickers:
            await self.refresh_market_data_func(rerun_request)
        whitelist = (
            self.supply_chain_whitelist_cls.from_candidate_whitelist(candidate_payload)
            if candidate_payload
            else None
        )
        return {
            "request": rerun_request,
            "whitelist": whitelist,
            "candidate_whitelist": candidate_payload,
            "candidate_revalidation": revalidation,
        }

    async def refresh_market_data(self, request: ReportRequest) -> dict:
        today = self.today_func()
        pipeline = self.ingestion_pipeline_cls()
        tickers = request.tickers
        return {
            "market": await pipeline.refresh_market(
                tickers,
                today - timedelta(days=max(request.lookback_days, 240)),
                today,
                filter_allowed=False,
            ),
            "monthly_revenue": await pipeline.refresh_monthly_revenue(
                tickers,
                today - timedelta(days=450),
                today,
                filter_allowed=False,
            ),
            "financial_metrics": await pipeline.refresh_financial_metrics(
                tickers,
                today - timedelta(days=365 * 6),
                today,
                filter_allowed=False,
            ),
            "valuations": await pipeline.refresh_valuations(
                tickers,
                today - timedelta(days=max(request.lookback_days, 30)),
                today,
                filter_allowed=False,
            ),
        }

    @staticmethod
    def _report_tickers(report: Any) -> list[str]:
        return _json_tickers(getattr(report, "tickers_json", ""))


def _json_tickers(tickers_json: str | None) -> list[str]:
    try:
        tickers = json.loads(tickers_json)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(ticker) for ticker in tickers if str(ticker).strip()]
