from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db.session import session_scope
from app.models.schemas import ReportRequest
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.discovery_workflow import (
    discovery_effective_lookback_days,
    discovery_market_history_days,
    discovery_valuation_history_days,
)
from app.services.persistence import ReportRepository
from app.services.llm_usage import record_llm_usage_from_report_execution
from app.services.report_generator import ReportGenerator, report_execution_summary
from app.services.report_quality import (
    attach_quality_gate_to_report,
    build_report_quality_gate,
    is_stale_market_data_source,
    summarize_document_source_quality,
    summarize_llm_status,
)
from app.services.source_quality import filter_formal_evidence_documents


def model_dump_json(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if not callable(dump):
        return value
    try:
        return dump(mode="json")
    except TypeError:
        return dump()


def leading_signal_covered_count(
    promoted_tickers: list[str],
    snapshots: list,
    latest_monthly_revenues: list,
    valuations: list,
) -> int:
    market_tickers = {snapshot.ticker for snapshot in snapshots}
    monthly_tickers = {revenue.ticker for revenue in latest_monthly_revenues}
    valuation_tickers = {valuation.ticker for valuation in valuations}
    return sum(
        1
        for ticker in promoted_tickers
        if ticker in market_tickers or ticker in monthly_tickers or ticker in valuation_tickers
    )


def stale_market_data_count(rows: list) -> int:
    return sum(1 for row in rows if is_stale_market_data_source(getattr(row, "source", "")))


def stale_financial_metric_ticker_count(metrics: list) -> int:
    return len(
        {
            str(getattr(metric, "ticker", ""))
            for metric in metrics
            if is_stale_market_data_source(getattr(metric, "source", ""))
        }
    )


class DiscoveredReportBuilderService:
    def __init__(
        self,
        session_scope_factory: Callable = session_scope,
        report_repository_cls=ReportRepository,
        report_generator_cls=ReportGenerator,
        report_request_cls=ReportRequest,
        report_execution_summary_func: Callable[[object], dict] = report_execution_summary,
        build_report_quality_gate_func: Callable = build_report_quality_gate,
        attach_quality_gate_to_report_func: Callable = attach_quality_gate_to_report,
        summarize_document_source_quality_func: Callable = summarize_document_source_quality,
        filter_formal_evidence_documents_func: Callable = filter_formal_evidence_documents,
        summarize_llm_status_func: Callable = summarize_llm_status,
        count_sufficient_company_filings_func: Callable[[list[str]], int] | None = None,
        candidate_revalidation_service_cls=CandidateRevalidationService,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.report_repository_cls = report_repository_cls
        self.report_generator_cls = report_generator_cls
        self.report_request_cls = report_request_cls
        self.report_execution_summary_func = report_execution_summary_func
        self.build_report_quality_gate_func = build_report_quality_gate_func
        self.attach_quality_gate_to_report_func = attach_quality_gate_to_report_func
        self.summarize_document_source_quality_func = summarize_document_source_quality_func
        self.filter_formal_evidence_documents_func = filter_formal_evidence_documents_func
        self.summarize_llm_status_func = summarize_llm_status_func
        self.count_sufficient_company_filings_func = (
            count_sufficient_company_filings_func
            or self._count_sufficient_company_filings
        )
        self.candidate_revalidation_service_cls = candidate_revalidation_service_cls

    def _count_sufficient_company_filings(self, tickers: list[str]) -> int:
        service = self.candidate_revalidation_service_cls(session_scope_factory=self.session_scope_factory)
        return len(service.sufficient_company_filing_tickers(tickers))

    def build_and_store_report(
        self,
        *,
        payload: Any,
        promoted_tickers: list[str],
        dynamic_whitelist: Any,
        documents: list,
        evidence_limit: int,
        source_audit: dict,
        discovery: dict,
        urls: list[str],
        ingestion_results: list[dict],
        fixed_source_ingestion: dict,
        dynamic_query_ingestion: list[dict],
        candidate_filing_ingestion: dict | None,
        company_filing_ingestion: dict,
        candidate_payload: list[dict],
        market_data: dict,
        run_id: int | None = None,
    ) -> dict:
        snapshots = market_data["snapshots"]
        price_history_snapshots = market_data["price_history_snapshots"]
        market_errors = market_data["market_errors"]
        monthly_revenues = market_data["monthly_revenues"]
        monthly_revenue_errors = market_data["monthly_revenue_errors"]
        latest_monthly_revenues = market_data["latest_monthly_revenues"]
        financial_metrics = market_data["financial_metrics"]
        financial_metric_errors = market_data["financial_metric_errors"]
        valuations = market_data["valuations"]
        valuation_errors = market_data["valuation_errors"]
        lookback_days = discovery_effective_lookback_days(payload)
        request = self.report_request_cls(
            topic=payload.topic,
            tickers=promoted_tickers,
            lookback_days=lookback_days,
            evidence_limit=evidence_limit,
            investor_capital=payload.investor_capital,
            beginner_mode=payload.beginner_mode,
            investor_profile=payload.investor_profile,
            max_position_pct=payload.max_position_pct,
            cash_reserve_pct=payload.cash_reserve_pct,
        )
        generator = self.report_generator_cls(whitelist=dynamic_whitelist)
        response = generator.generate(request, documents=documents)
        company_filing_sufficient_count = self.count_sufficient_company_filings_func(promoted_tickers)
        leading_signal_count = leading_signal_covered_count(
            promoted_tickers,
            snapshots,
            latest_monthly_revenues,
            valuations,
        )
        market_stale_count = stale_market_data_count(snapshots)
        monthly_revenue_stale_count = stale_market_data_count(latest_monthly_revenues)
        financial_metrics_stale_ticker_count = stale_financial_metric_ticker_count(financial_metrics)
        valuation_stale_count = stale_market_data_count(valuations)
        quality_gate = self.build_report_quality_gate_func(
            source_audit,
            promoted_tickers,
            market_count=len(snapshots),
            monthly_revenue_count=len(latest_monthly_revenues),
            financial_metrics_count=len(financial_metrics),
            valuation_count=len(valuations),
            investor_capital=payload.investor_capital,
            cash_reserve_pct=payload.cash_reserve_pct,
            source_quality=self.summarize_document_source_quality_func(
                self.filter_formal_evidence_documents_func(documents),
                lookback_days,
            ),
            plan_quality=source_audit.get("plan_quality"),
            leading_signal_count=leading_signal_count,
            llm_status=self.summarize_llm_status_func(generator.last_llm_result),
            company_filing_sufficient_count=company_filing_sufficient_count,
            market_stale_count=market_stale_count,
            monthly_revenue_stale_count=monthly_revenue_stale_count,
            financial_metrics_stale_ticker_count=financial_metrics_stale_ticker_count,
            valuation_stale_count=valuation_stale_count,
        )
        response = self.attach_quality_gate_to_report_func(response, quality_gate)
        with self.session_scope_factory() as session:
            report = self.report_repository_cls(session).create(request, response)
            report_id = report.id
        report_execution = self.report_execution_summary_func(generator)
        record_llm_usage_from_report_execution(
            report_execution,
            operation="discovered_report_generation",
            report_id=report_id,
            run_id=run_id,
            session_scope_factory=self.session_scope_factory,
        )
        run_payload = {
            "request": request.model_dump(mode="json"),
            "discovery": discovery,
            "queries": urls,
            "ingestion": ingestion_results,
            "fixed_source_ingestion": fixed_source_ingestion,
            "dynamic_query_ingestion": dynamic_query_ingestion,
            "candidate_filing_ingestion": candidate_filing_ingestion,
            "company_filing_ingestion": company_filing_ingestion,
            "source_audit": source_audit,
            "candidate_whitelist": candidate_payload,
            "market": [model_dump_json(snapshot) for snapshot in snapshots],
            "market_history_days": discovery_market_history_days(payload),
            "market_history_count": len(price_history_snapshots),
            "market_errors": [model_dump_json(error) for error in market_errors],
            "market_stale_count": market_stale_count,
            "monthly_revenue": [
                model_dump_json(revenue) for revenue in monthly_revenues
            ],
            "monthly_revenue_errors": [
                model_dump_json(error) for error in monthly_revenue_errors
            ],
            "latest_monthly_revenue": [
                model_dump_json(revenue) for revenue in latest_monthly_revenues
            ],
            "monthly_revenue_stale_count": monthly_revenue_stale_count,
            "financial_metrics_count": len(financial_metrics),
            "financial_metric_errors": [
                model_dump_json(error) for error in financial_metric_errors
            ],
            "financial_metrics_stale_ticker_count": financial_metrics_stale_ticker_count,
            "valuations": [model_dump_json(valuation) for valuation in valuations],
            "valuation_history_days": discovery_valuation_history_days(payload),
            "valuation_errors": [model_dump_json(error) for error in valuation_errors],
            "valuation_stale_count": valuation_stale_count,
            "quality_gate": quality_gate,
            "report_execution": report_execution,
        }
        return {
            "request": request,
            "response": response,
            "report_id": report_id,
            "quality_gate": quality_gate,
            "generator": generator,
            "report_execution": report_execution,
            "run_payload": run_payload,
            "leading_signal_count": leading_signal_count,
            "company_filing_sufficient_count": company_filing_sufficient_count,
        }
