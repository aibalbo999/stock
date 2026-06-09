from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.services.report_followup import (
    candidate_audit_from_run_payload,
    parse_run_payload,
    plan_quality_from_quality_gate,
    summarize_candidate_support_payload,
)


def latest_report_update_target(
    schedule_payload: dict[str, Any],
    *,
    session_scope_factory: Callable[[], Any],
    report_repository_cls: Callable[[Any], Any],
    analysis_run_repository_cls: Callable[[Any], Any],
    context_service_factory: Callable[[], Any],
    normalize_tickers_func: Callable[[Iterable[Any]], list[str]],
    json_tickers_func: Callable[[str | None], list[str]],
) -> dict[str, Any]:
    with session_scope_factory() as session:
        reports = report_repository_cls(session).latest(1)
        if not reports:
            raise RuntimeError("after-close update requires at least one generated report")
        report = reports[0]
        run = analysis_run_repository_cls(session).get_by_report_id(report.id)
        run_payload = parse_run_payload(run.payload_json if run is not None else None)
        report_tickers = json_tickers_func(report.tickers_json)
    context = context_service_factory().load(report.id)
    request = context["request"]
    candidate_tickers = normalize_tickers_func(
        item.get("ticker")
        for item in (
            context.get("candidate_whitelist") or candidate_audit_from_run_payload(run_payload)
        )
        if isinstance(item, dict)
    )
    configured_tickers = normalize_tickers_func(schedule_payload.get("tickers") or [])
    tickers = configured_tickers or normalize_tickers_func(
        [
            *report_tickers,
            *getattr(request, "tickers", []),
            *candidate_tickers,
        ]
    )
    if not tickers:
        raise RuntimeError(f"after-close update could not resolve tickers for report {report.id}")
    lookback_days = int(
        schedule_payload.get("lookback_days") or getattr(request, "lookback_days", None) or 120
    )
    return {
        "report_id": report.id,
        "topic": report.topic,
        "generated_at": report.generated_at.isoformat(),
        "run_payload": run_payload,
        "context": context,
        "request": request.model_copy(update={"tickers": tickers, "lookback_days": lookback_days}),
        "tickers": tickers,
    }


async def refresh_after_close_data(
    target: dict[str, Any],
    schedule_payload: dict[str, Any],
    *,
    pipeline_factory: Callable[[int | None], Any],
    today_func: Callable[[], Any],
    run_id: int | None = None,
) -> dict[str, Any]:
    today = today_func()
    request = target["request"]
    tickers = target["tickers"]
    lookback_days = max(int(getattr(request, "lookback_days", 120) or 120), 120)
    pipeline = pipeline_factory(run_id)
    market = await pipeline.refresh_market(
        tickers,
        today - timedelta(days=lookback_days),
        today,
        filter_allowed=False,
    )
    monthly_revenue = await pipeline.refresh_monthly_revenue(
        tickers,
        today - timedelta(days=450),
        today,
        filter_allowed=False,
    )
    financial_metrics = await pipeline.refresh_financial_metrics(
        tickers,
        today - timedelta(days=365 * 6),
        today,
        filter_allowed=False,
    )
    valuations = await pipeline.refresh_valuations(
        tickers,
        today - timedelta(days=max(lookback_days, 30)),
        today,
        filter_allowed=False,
    )
    company_filings = {"status": "skipped", "reason": "refresh_company_filings=false"}
    if bool(schedule_payload.get("refresh_company_filings", True)):
        company_filings = await pipeline.ingest_company_filings(
            tickers,
            limit_per_query=2,
            filter_allowed=False,
        )
    return {
        "market": market,
        "monthly_revenue": monthly_revenue,
        "financial_metrics": financial_metrics,
        "valuations": valuations,
        "company_filings": company_filings,
    }


def rerun_after_close_report(
    target: dict[str, Any],
    *,
    report_build_service_factory: Callable[[], Any],
    supply_chain_whitelist_cls: Any,
    count_sufficient_company_filings_func: Callable[[list[str]], int],
    create_report_with_retention_func: Callable[[Any, Any], tuple[int, dict]],
    write_report_file_with_retention_func: Callable[[Any, Any], dict],
    combined_report_retention_func: Callable[[dict | None, dict | None], dict],
    record_llm_usage_func: Callable[..., Any],
) -> dict[str, Any]:
    request = target["request"]
    context = target["context"]
    candidates = context.get("candidate_whitelist") or []
    whitelist = (
        supply_chain_whitelist_cls.from_candidate_whitelist(candidates) if candidates else None
    )
    run_payload = context.get("run_payload") or target.get("run_payload") or {}
    report_result = report_build_service_factory().build(
        request,
        whitelist=whitelist,
        company_filing_sufficient_count=count_sufficient_company_filings_func(request.tickers),
        candidate_support=summarize_candidate_support_payload(candidates),
        plan_quality=(
            run_payload.get("plan_quality")
            or (run_payload.get("discovery") or {}).get("plan_quality")
            or plan_quality_from_quality_gate(context.get("quality_gate") or {})
        ),
    )
    response = report_result["response"]
    report_id, db_retention = create_report_with_retention_func(request, response)
    record_llm_usage_func(
        report_result.get("report_execution"),
        operation="after_close_report_rerun",
        report_id=report_id,
    )
    file_retention = write_report_file_with_retention_func(request, response)
    path = file_retention["path"]
    retention = combined_report_retention_func(db_retention, file_retention)
    return {
        "status": "generated",
        "report_id": report_id,
        "path": str(path),
        "retention": retention,
        "quality_gate": report_result["quality_gate"],
        "report_execution": report_result["report_execution"],
        "evidence_count": report_result["evidence_count"],
    }


def coverage_after_close_update(
    target: dict[str, Any],
    *,
    session_scope_factory: Callable[[], Any],
    market_repository_cls: Callable[[Any], Any],
    monthly_revenue_repository_cls: Callable[[Any], Any],
    valuation_metric_repository_cls: Callable[[Any], Any],
    financial_metric_repository_cls: Callable[[Any], Any],
    audit_company_data_func: Callable[..., dict],
) -> dict[str, Any]:
    tickers = target["tickers"]
    with session_scope_factory() as session:
        market = market_repository_cls(session).latest_by_tickers(tickers)
        monthly = monthly_revenue_repository_cls(session).latest_by_tickers(tickers)
        valuations = valuation_metric_repository_cls(session).latest_by_tickers(tickers)
        financials = financial_metric_repository_cls(session).by_tickers(tickers)
        audit = audit_company_data_func(
            session,
            tickers,
            markdown=target["context"].get("markdown") or "",
            run_payload=target.get("run_payload") or {},
        )
    financial_latest: dict[str, str] = {}
    for metric in financials:
        current = financial_latest.get(metric.ticker)
        report_date = metric.report_date.isoformat()
        if current is None or report_date > current:
            financial_latest[metric.ticker] = report_date
    return {
        "latest_dates": {
            "market": {item.ticker: item.trade_date.isoformat() for item in market},
            "monthly_revenue": {item.ticker: item.revenue_date.isoformat() for item in monthly},
            "financial_metrics": financial_latest,
            "valuations": {item.ticker: item.trade_date.isoformat() for item in valuations},
        },
        "coverage": {
            "market": len(market) / len(tickers) if tickers else 0,
            "monthly_revenue": len(monthly) / len(tickers) if tickers else 0,
            "financial_metrics": len(financial_latest) / len(tickers) if tickers else 0,
            "valuations": len(valuations) / len(tickers) if tickers else 0,
        },
        "company_data_audit": audit,
    }


def combined_report_retention(
    db_retention: dict | None, file_retention: dict | None
) -> dict[str, Any]:
    db_retention = dict(db_retention or {})
    file_retention = dict(file_retention or {})
    artifact_retention = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in file_retention.items()
    }
    artifact_retention = {
        **artifact_retention,
        "path": artifact_retention.get("path"),
    }
    return {
        "policy": "latest_per_topic",
        "db": db_retention,
        "artifacts": artifact_retention,
        "old_report_versions_deleted": int(db_retention.get("old_report_versions_deleted") or 0),
        "old_report_files_deleted": int(file_retention.get("old_report_files_deleted") or 0),
    }
