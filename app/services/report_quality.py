from __future__ import annotations

from datetime import date

from app.db.session import session_scope
from app.models.schemas import NewsDocument, ReportRequest
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignalAnalyzer
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.report_orchestrator import build_quality_recovery_plan
from app.services.report_quality_action_policy import quality_gate_action_policy
from app.services.report_quality_coverage_rules import (
    coverage_quality_notes as coverage_quality_notes,
)
from app.services.report_quality_recovery import (
    quality_remediation_actions,
    should_recover_market_data_quality as should_recover_market_data_quality,
)
from app.services.report_quality_runtime import (
    rag_runtime_status,
    summarize_llm_status,
)
from app.services.report_quality_issue_rules import quality_gate_issue_notes
from app.services.report_quality_llm_rules import llm_quality_notes as llm_quality_notes
from app.services.report_quality_market_rules import (
    market_coverage_quality_notes as market_coverage_quality_notes,
    market_rescue_quality_notes as market_rescue_quality_notes,
    market_trade_date_quality_notes as market_trade_date_quality_notes,
)
from app.services.report_quality_metrics import quality_gate_metrics
from app.services.report_quality_plan_rules import (
    discovery_plan_quality_notes as discovery_plan_quality_notes,
)
from app.services.report_quality_rag_rules import (
    normalized_rag_reranker_provider,
    rag_quality_warnings as rag_quality_warnings,
)
from app.services.report_quality_relevance_rules import (
    adjusted_source_relevance_counts as adjusted_source_relevance_counts,
    source_relevance_notes as source_relevance_notes,
)
from app.services.report_quality_sources import (
    LATEST_ONLY_MARKET_SOURCE_MARKER,
    STALE_MARKET_SOURCE_MARKER,
    is_latest_only_market_data_source,
    is_stale_market_data_source,
    latest_only_financial_metric_ticker_count as _latest_only_financial_metric_ticker_count,
    latest_only_market_data_count as _latest_only_market_data_count,
    market_provider_summary,
    market_trade_date_summary,
    source_quality_notes as source_quality_notes,
    stale_financial_metric_ticker_count as _stale_financial_metric_ticker_count,
    stale_market_data_count as _stale_market_data_count,
    summarize_document_source_quality,
)
from app.services.report_quality_markdown import (
    _first_matching_field as _first_matching_field,
    _first_matching_value as _first_matching_value,
    _format_confidence_score as _format_confidence_score,
    _format_llm_observability as _format_llm_observability,
    _format_llm_status as _format_llm_status,
    _format_market_provider_summary as _format_market_provider_summary,
    _format_optional_int as _format_optional_int,
    _format_optional_number as _format_optional_number,
    _format_optional_percent as _format_optional_percent,
    _format_plan_quality as _format_plan_quality,
    _format_rag_status as _format_rag_status,
    _investor_friendly_issue as _investor_friendly_issue,
    _markdown_section as _markdown_section,
    _parse_amount as _parse_amount,
    _parse_confidence_value as _parse_confidence_value,
    _parse_int as _parse_int,
    _parse_llm_status as _parse_llm_status,
    _parse_optional_int as _parse_optional_int,
    _parse_optional_percent as _parse_optional_percent,
    _parse_percent as _parse_percent,
    _parse_plan_quality_score as _parse_plan_quality_score,
    _parse_plan_quality_status as _parse_plan_quality_status,
    _parse_stale_metric_count as _parse_stale_metric_count,
    _split_issue_field as _split_issue_field,
    attach_quality_gate_to_report as attach_quality_gate_to_report,
    parse_quality_gate_from_markdown as parse_quality_gate_from_markdown,
    remove_quality_gate_sections as remove_quality_gate_sections,
    render_quality_action_guard_markdown as render_quality_action_guard_markdown,
    render_quality_gate_markdown as render_quality_gate_markdown,
)

__all__ = [
    "LATEST_ONLY_MARKET_SOURCE_MARKER",
    "STALE_MARKET_SOURCE_MARKER",
    "is_latest_only_market_data_source",
    "is_stale_market_data_source",
    "market_provider_summary",
    "market_trade_date_summary",
    "summarize_document_source_quality",
]


def build_report_quality_gate(
    source_audit: dict,
    promoted_tickers: list[str],
    market_count: int,
    monthly_revenue_count: int,
    financial_metrics_count: int,
    valuation_count: int,
    investor_capital: int | None = None,
    cash_reserve_pct: float | None = None,
    source_quality: dict | None = None,
    plan_quality: dict | None = None,
    leading_signal_count: int | None = None,
    llm_status: dict | None = None,
    company_filing_sufficient_count: int | None = None,
    market_stale_count: int = 0,
    monthly_revenue_stale_count: int = 0,
    financial_metrics_stale_ticker_count: int = 0,
    valuation_stale_count: int = 0,
    market_latest_only_count: int = 0,
    monthly_revenue_latest_only_count: int = 0,
    financial_metrics_latest_only_ticker_count: int = 0,
    valuation_latest_only_count: int = 0,
    rag_status: dict | None = None,
    market_provider_summary: dict | None = None,
    market_latest_trade_date: date | str | None = None,
    market_latest_trade_date_coverage: float | None = None,
    market_database_latest_trade_date: date | str | None = None,
    market_older_than_database_latest_count: int = 0,
    market_max_trade_date_lag_days: int | None = None,
) -> dict:
    candidate_support = source_audit.get("candidate_support") or {}
    dynamic_sources = source_audit.get("dynamic_queries") or {}
    promoted_count = len(promoted_tickers)
    source_count = max(
        int(dynamic_sources.get("stored_count") or 0),
        int(source_audit.get("total_stored_count") or 0),
    )
    source_quality = source_quality or {}
    plan_quality = plan_quality or source_audit.get("plan_quality") or {}
    exploration_supported_ratio = float(
        candidate_support.get(
            "exploration_supported_ratio", candidate_support.get("supported_ratio")
        )
        or 0
    )
    formal_supported_ratio = float(
        candidate_support.get(
            "formal_supported_ratio",
            1.0 if promoted_count else exploration_supported_ratio,
        )
        or 0
    )
    formal_confidence_avg = candidate_support.get("formal_confidence_avg")
    formal_confidence_min = candidate_support.get("formal_confidence_min")
    formal_low_confidence_count = int(candidate_support.get("formal_low_confidence_count") or 0)
    market_coverage = market_count / promoted_count if promoted_count else 0
    monthly_coverage = monthly_revenue_count / promoted_count if promoted_count else 0
    valuation_coverage = valuation_count / promoted_count if promoted_count else 0
    market_fresh_coverage = (
        max(0, market_count - market_stale_count) / promoted_count if promoted_count else 0
    )
    monthly_fresh_coverage = (
        max(0, monthly_revenue_count - monthly_revenue_stale_count) / promoted_count
        if promoted_count
        else 0
    )
    valuation_fresh_coverage = (
        max(0, valuation_count - valuation_stale_count) / promoted_count if promoted_count else 0
    )
    leading_signal_coverage = (
        leading_signal_count / promoted_count
        if promoted_count and leading_signal_count is not None
        else None
    )
    company_filing_coverage = (
        company_filing_sufficient_count / promoted_count
        if promoted_count and company_filing_sufficient_count is not None
        else None
    )
    llm_status = llm_status or {}
    llm_fallback = bool(llm_status.get("fallback")) if llm_status else None
    source_relevance = source_audit.get("source_relevance") or {}
    rag_status = rag_status or {}
    llm_observability = (llm_status or {}).get("observability") or {}
    rag_embedding_status = rag_status.get("embedding_status") or {}
    rag_reranker_status = rag_status.get("reranker_status") or {}
    rag_reranker_provider = normalized_rag_reranker_provider(rag_reranker_status)
    rag_retrieval_status = rag_status.get("retrieval_status") or {}
    market_provider_summary = market_provider_summary or {}
    stale_market_dataset_count = (
        int(market_stale_count)
        + int(monthly_revenue_stale_count)
        + int(financial_metrics_stale_ticker_count)
        + int(valuation_stale_count)
    )
    latest_only_market_dataset_count = (
        int(market_latest_only_count)
        + int(monthly_revenue_latest_only_count)
        + int(financial_metrics_latest_only_ticker_count)
        + int(valuation_latest_only_count)
    )

    issue_notes = quality_gate_issue_notes(
        promoted_count=promoted_count,
        exploration_supported_ratio=exploration_supported_ratio,
        formal_supported_ratio=formal_supported_ratio,
        formal_low_confidence_count=formal_low_confidence_count,
        source_count=source_count,
        source_relevance=source_relevance,
        source_quality=source_quality,
        plan_quality=plan_quality,
        market_count=market_count,
        monthly_revenue_count=monthly_revenue_count,
        financial_metrics_count=financial_metrics_count,
        valuation_count=valuation_count,
        market_coverage=market_coverage,
        monthly_coverage=monthly_coverage,
        valuation_coverage=valuation_coverage,
        market_latest_trade_date=market_latest_trade_date,
        market_database_latest_trade_date=market_database_latest_trade_date,
        market_max_trade_date_lag_days=market_max_trade_date_lag_days,
        market_latest_trade_date_coverage=market_latest_trade_date_coverage,
        market_older_than_database_latest_count=market_older_than_database_latest_count,
        market_stale_count=market_stale_count,
        monthly_revenue_stale_count=monthly_revenue_stale_count,
        financial_metrics_stale_ticker_count=financial_metrics_stale_ticker_count,
        valuation_stale_count=valuation_stale_count,
        stale_market_dataset_count=stale_market_dataset_count,
        market_latest_only_count=market_latest_only_count,
        monthly_revenue_latest_only_count=monthly_revenue_latest_only_count,
        financial_metrics_latest_only_ticker_count=financial_metrics_latest_only_ticker_count,
        valuation_latest_only_count=valuation_latest_only_count,
        latest_only_market_dataset_count=latest_only_market_dataset_count,
        leading_signal_coverage=leading_signal_coverage,
        company_filing_coverage=company_filing_coverage,
        llm_status=llm_status,
        rag_status=rag_status,
    )
    blockers = issue_notes["blockers"]
    warnings = issue_notes["warnings"]
    observations = issue_notes["observations"]
    missing_subtopic_count = issue_notes["missing_subtopic_count"]
    weak_subtopic_count = issue_notes["weak_subtopic_count"]
    market_trade_date_lag_days = issue_notes["market_trade_date_lag_days"]
    market_trade_date_warning_suppressed = issue_notes["market_trade_date_warning_suppressed"]

    status, action_policy = quality_gate_action_policy(
        blockers=blockers,
        warnings=warnings,
        investor_capital=investor_capital,
        cash_reserve_pct=cash_reserve_pct,
    )
    remediation_actions = quality_remediation_actions(blockers, warnings)
    quality_gate = {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "observations": observations,
        "remediation_actions": remediation_actions,
        "action_policy": action_policy,
        "metrics": quality_gate_metrics(
            promoted_count=promoted_count,
            formal_supported_ratio=formal_supported_ratio,
            exploration_supported_ratio=exploration_supported_ratio,
            formal_confidence_avg=formal_confidence_avg,
            formal_confidence_min=formal_confidence_min,
            formal_low_confidence_count=formal_low_confidence_count,
            source_count=source_count,
            missing_subtopic_count=missing_subtopic_count,
            weak_subtopic_count=weak_subtopic_count,
            market_coverage=market_coverage,
            monthly_coverage=monthly_coverage,
            financial_metrics_count=financial_metrics_count,
            valuation_coverage=valuation_coverage,
            market_fresh_coverage=market_fresh_coverage,
            monthly_fresh_coverage=monthly_fresh_coverage,
            valuation_fresh_coverage=valuation_fresh_coverage,
            market_stale_count=market_stale_count,
            monthly_revenue_stale_count=monthly_revenue_stale_count,
            financial_metrics_stale_ticker_count=financial_metrics_stale_ticker_count,
            valuation_stale_count=valuation_stale_count,
            stale_market_dataset_count=stale_market_dataset_count,
            market_latest_only_count=market_latest_only_count,
            monthly_revenue_latest_only_count=monthly_revenue_latest_only_count,
            financial_metrics_latest_only_ticker_count=financial_metrics_latest_only_ticker_count,
            valuation_latest_only_count=valuation_latest_only_count,
            latest_only_market_dataset_count=latest_only_market_dataset_count,
            market_latest_trade_date=market_latest_trade_date,
            market_latest_trade_date_coverage=market_latest_trade_date_coverage,
            market_database_latest_trade_date=market_database_latest_trade_date,
            market_older_than_database_latest_count=market_older_than_database_latest_count,
            market_trade_date_lag_days=market_trade_date_lag_days,
            market_trade_date_warning_suppressed=market_trade_date_warning_suppressed,
            leading_signal_coverage=leading_signal_coverage,
            company_filing_coverage=company_filing_coverage,
            llm_status=llm_status,
            llm_fallback=llm_fallback,
            llm_observability=llm_observability,
            rag_status=rag_status,
            rag_embedding_status=rag_embedding_status,
            rag_reranker_status=rag_reranker_status,
            rag_reranker_provider=rag_reranker_provider,
            rag_retrieval_status=rag_retrieval_status,
            market_provider_summary=market_provider_summary,
            source_quality=source_quality,
            plan_quality=plan_quality,
        ),
        "recommendation": (
            "資料品質不足，請先視為研究草稿，不應作為買賣依據。"
            if status == "insufficient"
            else "資料大致可用，但仍需人工確認警示項。"
            if status == "caution"
            else "資料品質達到本系統產出投資建議的基本門檻。"
        ),
    }
    quality_gate["self_healing"] = build_quality_recovery_plan(
        blockers=blockers,
        warnings=warnings,
        metrics=quality_gate["metrics"],
        promoted_tickers=promoted_tickers,
    )
    return quality_gate


def _peer_valuation_summary(valuations) -> dict[str, float | None]:
    pe_values = [
        valuation.pe_ratio
        for valuation in valuations
        if valuation.pe_ratio is not None and valuation.pe_ratio > 0
    ]
    pb_values = [
        valuation.pb_ratio
        for valuation in valuations
        if valuation.pb_ratio is not None and valuation.pb_ratio > 0
    ]
    return {
        "pe_avg": sum(pe_values) / len(pe_values) if pe_values else None,
        "pb_avg": sum(pb_values) / len(pb_values) if pb_values else None,
    }


def build_quality_gate_for_request(
    request: ReportRequest,
    documents: list[NewsDocument] | None = None,
    source_count: int | None = None,
    llm_result: object | None = None,
    company_filing_sufficient_count: int | None = None,
    candidate_support: dict | None = None,
    plan_quality: dict | None = None,
) -> dict:
    tickers = list(dict.fromkeys(request.tickers))
    if not tickers:
        tickers = EntityMapper().filter_allowed_tickers(request.tickers)
    source_count = len(documents or []) if source_count is None else source_count
    source_quality = (
        summarize_document_source_quality(documents or [], request.lookback_days)
        if documents
        else None
    )
    source_audit = {
        "candidate_support": candidate_support
        or {
            "total": len(tickers),
            "supported": len(tickers),
            "unsupported": 0,
            "supported_ratio": 1.0 if tickers else 0.0,
        },
        "dynamic_queries": {"stored_count": source_count},
    }
    with session_scope() as session:
        snapshots = MarketRepository(session).latest_by_tickers(tickers)
        monthly_revenues = MonthlyRevenueRepository(session).latest_by_tickers(tickers)
        financial_metrics = FinancialMetricRepository(session).by_tickers(tickers)
        valuations = ValuationMetricRepository(session).latest_by_tickers(tickers)
        market_count = len(snapshots)
        monthly_revenue_count = len(monthly_revenues)
        financial_metrics_count = len(financial_metrics)
        valuation_count = len(valuations)
        market_stale_count = _stale_market_data_count(snapshots)
        monthly_revenue_stale_count = _stale_market_data_count(monthly_revenues)
        financial_metrics_stale_ticker_count = _stale_financial_metric_ticker_count(
            financial_metrics
        )
        valuation_stale_count = _stale_market_data_count(valuations)
        market_latest_only_count = _latest_only_market_data_count(snapshots)
        monthly_revenue_latest_only_count = _latest_only_market_data_count(monthly_revenues)
        financial_metrics_latest_only_ticker_count = _latest_only_financial_metric_ticker_count(
            financial_metrics
        )
        valuation_latest_only_count = _latest_only_market_data_count(valuations)
        market_repository = MarketRepository(session)
        latest_trade_date = (
            market_repository.latest_trade_date()
            if callable(getattr(market_repository, "latest_trade_date", None))
            else None
        )
        market_date_summary = market_trade_date_summary(
            snapshots,
            tickers,
            latest_trade_date,
        )
        price_histories = market_repository.history_by_tickers(tickers, limit=90)
        revenue_histories = MonthlyRevenueRepository(session).history_by_tickers(tickers, limit=18)
    valuation_map = {valuation.ticker: valuation for valuation in valuations}
    peer_summary = _peer_valuation_summary(valuations)
    leading_signals = LeadingSignalAnalyzer().build(
        tickers, price_histories, revenue_histories, valuation_map, peer_summary
    )
    leading_signal_count = sum(1 for signal in leading_signals.values() if signal.has_signal_data)
    return build_report_quality_gate(
        source_audit,
        tickers,
        market_count=market_count,
        monthly_revenue_count=monthly_revenue_count,
        financial_metrics_count=financial_metrics_count,
        valuation_count=valuation_count,
        investor_capital=request.investor_capital,
        cash_reserve_pct=request.cash_reserve_pct,
        source_quality=source_quality,
        plan_quality=plan_quality,
        leading_signal_count=leading_signal_count,
        llm_status=summarize_llm_status(llm_result),
        company_filing_sufficient_count=company_filing_sufficient_count,
        market_stale_count=market_stale_count,
        monthly_revenue_stale_count=monthly_revenue_stale_count,
        financial_metrics_stale_ticker_count=financial_metrics_stale_ticker_count,
        valuation_stale_count=valuation_stale_count,
        market_latest_only_count=market_latest_only_count,
        monthly_revenue_latest_only_count=monthly_revenue_latest_only_count,
        financial_metrics_latest_only_ticker_count=financial_metrics_latest_only_ticker_count,
        valuation_latest_only_count=valuation_latest_only_count,
        rag_status=rag_runtime_status(),
        market_provider_summary=market_provider_summary(
            snapshots,
            monthly_revenues,
            financial_metrics,
            valuations,
        ),
        market_latest_trade_date=market_date_summary["latest_trade_date"],
        market_latest_trade_date_coverage=market_date_summary["latest_trade_date_coverage"],
        market_database_latest_trade_date=market_date_summary["database_latest_trade_date"],
        market_older_than_database_latest_count=market_date_summary[
            "older_than_database_latest_count"
        ],
        market_max_trade_date_lag_days=market_date_summary["max_trade_date_lag_days"],
    )
