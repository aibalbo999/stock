from __future__ import annotations

from datetime import date

from app.services.report_quality_coverage_rules import coverage_quality_notes
from app.services.report_quality_llm_rules import llm_quality_notes
from app.services.report_quality_market_rules import (
    market_coverage_quality_notes,
    market_rescue_quality_notes,
    market_trade_date_quality_notes,
)
from app.services.report_quality_plan_rules import discovery_plan_quality_notes
from app.services.report_quality_rag_rules import rag_quality_warnings
from app.services.report_quality_relevance_rules import (
    adjusted_source_relevance_counts,
    source_relevance_notes,
)
from app.services.report_quality_sources import date_lag_days, source_quality_notes


def quality_gate_issue_notes(
    *,
    promoted_count: int,
    exploration_supported_ratio: float,
    formal_supported_ratio: float,
    formal_low_confidence_count: int,
    source_count: int,
    source_relevance: dict,
    source_quality: dict,
    plan_quality: dict,
    market_count: int,
    monthly_revenue_count: int,
    financial_metrics_count: int,
    valuation_count: int,
    market_coverage: float,
    monthly_coverage: float,
    valuation_coverage: float,
    market_latest_trade_date: date | str | None,
    market_database_latest_trade_date: date | str | None,
    market_max_trade_date_lag_days: int | None,
    market_latest_trade_date_coverage: float | None,
    market_older_than_database_latest_count: int,
    market_stale_count: int,
    monthly_revenue_stale_count: int,
    financial_metrics_stale_ticker_count: int,
    valuation_stale_count: int,
    stale_market_dataset_count: int,
    market_latest_only_count: int,
    monthly_revenue_latest_only_count: int,
    financial_metrics_latest_only_ticker_count: int,
    valuation_latest_only_count: int,
    latest_only_market_dataset_count: int,
    leading_signal_coverage: float | None,
    company_filing_coverage: float | None,
    llm_status: dict,
    rag_status: dict,
) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    observations: list[str] = []
    if promoted_count == 0:
        blockers.append("沒有通過證據驗證的正式分析股票")
    if promoted_count == 0 and exploration_supported_ratio < 0.6:
        blockers.append("候選公司證據覆蓋率低於 60%")
    elif promoted_count and formal_supported_ratio < 1:
        blockers.append("正式分析股票仍含弱證據公司")
    elif promoted_count and formal_low_confidence_count:
        blockers.append("正式分析股票含低信心證據公司")
    elif promoted_count and exploration_supported_ratio < 0.6:
        observations.append("AI 初始候選清單較廣，已由二次篩選收斂為正式分析股票")
    if source_count < 8:
        blockers.append("AI 動態資料來源入庫篇數過少")
    elif source_count < 12:
        warnings.append("AI 動態資料來源偏少")
    missing_subtopic_count, weak_subtopic_count = adjusted_source_relevance_counts(
        source_relevance,
        market_count=market_count,
        monthly_revenue_count=monthly_revenue_count,
        valuation_count=valuation_count,
        financial_metrics_count=financial_metrics_count,
    )
    unique_publishers = int(source_quality.get("unique_publisher_count") or 0)
    _extend_issue_lists(
        blockers,
        warnings,
        observations,
        source_relevance_notes(
            missing_subtopic_count=missing_subtopic_count,
            weak_subtopic_count=weak_subtopic_count,
            source_count=source_count,
            unique_publishers=unique_publishers,
        ),
    )
    source_blockers, source_warnings = source_quality_notes(source_quality, source_count)
    blockers.extend(source_blockers)
    warnings.extend(source_warnings)
    plan_blockers, plan_warnings = discovery_plan_quality_notes(plan_quality)
    blockers.extend(plan_blockers)
    warnings.extend(plan_warnings)
    market_coverage_blockers, market_coverage_warnings = market_coverage_quality_notes(
        promoted_count=promoted_count,
        market_coverage=market_coverage,
        monthly_coverage=monthly_coverage,
        financial_metrics_count=financial_metrics_count,
        valuation_coverage=valuation_coverage,
    )
    blockers.extend(market_coverage_blockers)
    warnings.extend(market_coverage_warnings)
    market_trade_date_lag_days = _market_trade_date_lag_days(
        market_max_trade_date_lag_days,
        market_latest_trade_date,
        market_database_latest_trade_date,
    )
    market_trade_date_warning_suppressed = _market_trade_date_warning_suppressed(
        promoted_count=promoted_count,
        market_coverage=market_coverage,
        market_stale_count=market_stale_count,
        market_latest_only_count=market_latest_only_count,
        market_trade_date_lag_days=market_trade_date_lag_days,
    )
    market_trade_date_warnings, market_trade_date_observations = market_trade_date_quality_notes(
        promoted_count=promoted_count,
        market_latest_trade_date_coverage=market_latest_trade_date_coverage,
        market_older_than_database_latest_count=market_older_than_database_latest_count,
        market_trade_date_warning_suppressed=market_trade_date_warning_suppressed,
    )
    warnings.extend(market_trade_date_warnings)
    observations.extend(market_trade_date_observations)
    market_rescue_warnings, market_rescue_observations = market_rescue_quality_notes(
        stale_market_dataset_count=stale_market_dataset_count,
        market_stale_count=market_stale_count,
        monthly_revenue_stale_count=monthly_revenue_stale_count,
        financial_metrics_stale_ticker_count=financial_metrics_stale_ticker_count,
        valuation_stale_count=valuation_stale_count,
        latest_only_market_dataset_count=latest_only_market_dataset_count,
        market_latest_only_count=market_latest_only_count,
        monthly_revenue_latest_only_count=monthly_revenue_latest_only_count,
        financial_metrics_latest_only_ticker_count=financial_metrics_latest_only_ticker_count,
        valuation_latest_only_count=valuation_latest_only_count,
    )
    warnings.extend(market_rescue_warnings)
    observations.extend(market_rescue_observations)
    coverage_warnings, coverage_observations = coverage_quality_notes(
        promoted_count=promoted_count,
        leading_signal_coverage=leading_signal_coverage,
        company_filing_coverage=company_filing_coverage,
    )
    warnings.extend(coverage_warnings)
    observations.extend(coverage_observations)
    llm_warnings, llm_observations = llm_quality_notes(llm_status)
    warnings.extend(llm_warnings)
    observations.extend(llm_observations)
    warnings.extend(rag_quality_warnings(rag_status))
    return {
        "blockers": blockers,
        "warnings": warnings,
        "observations": observations,
        "missing_subtopic_count": missing_subtopic_count,
        "weak_subtopic_count": weak_subtopic_count,
        "market_trade_date_lag_days": market_trade_date_lag_days,
        "market_trade_date_warning_suppressed": market_trade_date_warning_suppressed,
    }


def _extend_issue_lists(
    blockers: list[str],
    warnings: list[str],
    observations: list[str],
    notes: tuple[list[str], list[str], list[str]],
) -> None:
    note_blockers, note_warnings, note_observations = notes
    blockers.extend(note_blockers)
    warnings.extend(note_warnings)
    observations.extend(note_observations)


def _market_trade_date_lag_days(
    market_max_trade_date_lag_days: int | None,
    market_latest_trade_date: date | str | None,
    market_database_latest_trade_date: date | str | None,
) -> int | None:
    if market_max_trade_date_lag_days is not None:
        return market_max_trade_date_lag_days
    return date_lag_days(market_latest_trade_date, market_database_latest_trade_date)


def _market_trade_date_warning_suppressed(
    *,
    promoted_count: int,
    market_coverage: float,
    market_stale_count: int,
    market_latest_only_count: int,
    market_trade_date_lag_days: int | None,
) -> bool:
    return bool(
        promoted_count
        and market_coverage >= 1
        and not market_stale_count
        and not market_latest_only_count
        and market_trade_date_lag_days is not None
        and market_trade_date_lag_days <= 1
    )


__all__ = ["quality_gate_issue_notes"]
