from __future__ import annotations


def discovered_pipeline_result_payload(
    *,
    run_id: int,
    run_record_updated: bool,
    report_id: int,
    active_report_id: int,
    auto_follow_up: dict,
    discovery: dict,
    queries: list,
    fixed_source_ingestion: dict,
    dynamic_query_ingestion: list,
    candidate_filing_ingestion: dict | None,
    company_filing_ingestion: dict,
    source_audit: dict,
    candidate_whitelist: list[dict],
    promoted_tickers: list[str],
    run_payload: dict,
    quality_gate: dict,
    report_execution: dict,
    request: dict,
    topic: str | None,
    report: dict,
    resumed_from_step: str | None = None,
) -> dict:
    result = {
        "run_id": run_id,
        "run_record_updated": run_record_updated,
        "report_id": report_id,
        "active_report_id": active_report_id,
        "auto_follow_up": auto_follow_up,
        "discovery": discovery,
        "queries": queries,
        "fixed_source_ingestion": fixed_source_ingestion,
        "dynamic_query_ingestion": dynamic_query_ingestion,
        "candidate_filing_ingestion": candidate_filing_ingestion,
        "company_filing_ingestion": company_filing_ingestion,
        "source_audit": source_audit,
        "candidate_whitelist": candidate_whitelist,
        "promoted_tickers": promoted_tickers,
        "market": run_payload.get("market") or [],
        "market_history_count": run_payload.get("market_history_count", 0),
        "market_errors": run_payload.get("market_errors") or [],
        "monthly_revenue": run_payload.get("monthly_revenue") or [],
        "monthly_revenue_errors": run_payload.get("monthly_revenue_errors") or [],
        "latest_monthly_revenue": run_payload.get("latest_monthly_revenue") or [],
        "financial_metrics_count": run_payload.get("financial_metrics_count", 0),
        "financial_metric_errors": run_payload.get("financial_metric_errors") or [],
        "valuations": run_payload.get("valuations") or [],
        "valuation_errors": run_payload.get("valuation_errors") or [],
        "quality_gate": quality_gate,
        "report_execution": report_execution,
        "request": request,
        "topic": topic,
        "report": report,
    }
    if resumed_from_step:
        result["resumed_from_step"] = resumed_from_step
    return result


__all__ = ["discovered_pipeline_result_payload"]
