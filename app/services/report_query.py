from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from app.services.candidate_audit import (
    candidate_audit_summary,
    render_candidate_audit_markdown,
)
from app.services.candidate_revalidation import sanitize_candidate_low_quality_sources
from app.services.persistence import AnalysisRunRepository, ReportRepository
from app.services.report_followup import (
    append_candidate_audit_if_missing,
    candidate_audit_from_run_payload,
    latest_follow_up_run_for_report,
    parse_run_payload,
    request_from_report_record,
    report_tickers,
    sync_candidate_audit_section,
)
from app.models.schemas import ReportRequest, ReportResponse
from app.services.report_quality import (
    attach_quality_gate_to_report,
    build_quality_gate_for_request,
    parse_quality_gate_from_markdown,
)
from app.services.source_quality import remove_low_quality_investor_forum_lines


def _quality_gate_refresh_kwargs(metrics: dict, promoted_count: int) -> dict:
    kwargs: dict[str, Any] = {}
    source_count = _metric_int(metrics.get("dynamic_source_count"))
    if source_count is not None:
        kwargs["source_count"] = source_count

    company_filing_coverage = _metric_float(metrics.get("company_filing_coverage"))
    if company_filing_coverage is not None:
        kwargs["company_filing_sufficient_count"] = round(company_filing_coverage * promoted_count)

    candidate_supported_ratio = _metric_float(metrics.get("candidate_supported_ratio"), 1.0 if promoted_count else 0.0)
    exploration_supported_ratio = _metric_float(
        metrics.get("exploration_candidate_supported_ratio"),
        candidate_supported_ratio,
    )
    kwargs["candidate_support"] = {
        "total": promoted_count,
        "supported": round(candidate_supported_ratio * promoted_count),
        "unsupported": max(0, promoted_count - round(candidate_supported_ratio * promoted_count)),
        "supported_ratio": candidate_supported_ratio,
        "formal_supported_ratio": candidate_supported_ratio,
        "exploration_supported_ratio": exploration_supported_ratio,
        "formal_confidence_avg": metrics.get("formal_confidence_avg"),
        "formal_confidence_min": metrics.get("formal_confidence_min"),
    }

    plan_quality = {
        "status": metrics.get("discovery_plan_status"),
        "score": metrics.get("discovery_plan_score"),
    }
    if plan_quality["status"] or plan_quality["score"] is not None:
        kwargs["plan_quality"] = plan_quality
    return kwargs


def _quality_gate_from_report(report: Any, markdown: str, parse_quality_gate_func: Callable[[str], dict]) -> dict | None:
    stored_payload = getattr(report, "quality_gate_json", None)
    if stored_payload:
        try:
            quality_gate = json.loads(stored_payload)
        except (TypeError, json.JSONDecodeError):
            quality_gate = None
        if isinstance(quality_gate, dict):
            return quality_gate
    return parse_quality_gate_func(markdown)


def _metric_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _metric_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ReportQueryNotFound(ValueError):
    pass


class ReportQueryService:
    def __init__(
        self,
        *,
        session_scope_factory: Callable[[], AbstractContextManager],
        report_repository_cls: type[ReportRepository] = ReportRepository,
        analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
        parse_run_payload_func: Callable[[str | None], dict] = parse_run_payload,
        candidate_audit_from_run_payload_func: Callable[[dict], list[dict]] = candidate_audit_from_run_payload,
        latest_follow_up_run_for_report_func: Callable[[Any, Any, Any | None], dict | None] = latest_follow_up_run_for_report,
        remove_low_quality_lines_func: Callable[[str], str] = remove_low_quality_investor_forum_lines,
        append_candidate_audit_func: Callable[[str, list[dict], list[str]], str] = append_candidate_audit_if_missing,
        sync_candidate_audit_func: Callable[[str, list[dict], list[str]], str] = sync_candidate_audit_section,
        sanitize_candidates_func: Callable[[list[dict]], list[dict]] = sanitize_candidate_low_quality_sources,
        parse_quality_gate_func: Callable[[str], dict] = parse_quality_gate_from_markdown,
        build_quality_gate_for_request_func: Callable[..., dict] = build_quality_gate_for_request,
        attach_quality_gate_to_report_func: Callable[[ReportResponse, dict], ReportResponse] = attach_quality_gate_to_report,
        candidate_audit_summary_func: Callable[[list[dict], list[str]], dict] = candidate_audit_summary,
        render_candidate_audit_markdown_func: Callable[[list[dict], list[str]], str] = render_candidate_audit_markdown,
        report_tickers_func: Callable[[Any], list[str]] = report_tickers,
    ) -> None:
        self.session_scope_factory = session_scope_factory
        self.report_repository_cls = report_repository_cls
        self.analysis_run_repository_cls = analysis_run_repository_cls
        self.parse_run_payload_func = parse_run_payload_func
        self.candidate_audit_from_run_payload_func = candidate_audit_from_run_payload_func
        self.latest_follow_up_run_for_report_func = latest_follow_up_run_for_report_func
        self.remove_low_quality_lines_func = remove_low_quality_lines_func
        self.append_candidate_audit_func = append_candidate_audit_func
        self.sync_candidate_audit_func = sync_candidate_audit_func
        self.sanitize_candidates_func = sanitize_candidates_func
        self.parse_quality_gate_func = parse_quality_gate_func
        self.build_quality_gate_for_request_func = build_quality_gate_for_request_func
        self.attach_quality_gate_to_report_func = attach_quality_gate_to_report_func
        self.candidate_audit_summary_func = candidate_audit_summary_func
        self.render_candidate_audit_markdown_func = render_candidate_audit_markdown_func
        self.report_tickers_func = report_tickers_func

    def list_reports(self, limit: int = 20) -> list[dict]:
        with self.session_scope_factory() as session:
            repository = self.report_repository_cls(session)
            latest_by_topic = getattr(repository, "latest_by_topic", None)
            reports = latest_by_topic(limit) if callable(latest_by_topic) else repository.latest(limit)
        return [
            {
                "id": report.id,
                "title": report.title,
                "topic": report.topic,
                "generated_at": report.generated_at.isoformat(),
                "retention_policy": "latest_per_topic",
            }
            for report in reports
        ]

    def quality_summary(self, limit: int = 20) -> dict:
        safe_limit = max(1, min(int(limit or 20), 100))
        with self.session_scope_factory() as session:
            repository = self.report_repository_cls(session)
            latest_by_topic = getattr(repository, "latest_by_topic", None)
            reports = latest_by_topic(safe_limit) if callable(latest_by_topic) else repository.latest(safe_limit)
        rows = [self._quality_summary_row(report) for report in reports]
        status_counts = _count_values(rows, "status")
        blocker_count = sum(int(row.get("blocker_count") or 0) for row in rows)
        warning_count = sum(int(row.get("warning_count") or 0) for row in rows)
        status = (
            "no_reports"
            if not rows
            else "insufficient"
            if status_counts.get("insufficient") or blocker_count
            else "caution"
            if status_counts.get("caution") or status_counts.get("unknown") or warning_count
            else "ready"
        )
        confidence_values = [
            float(row["formal_confidence_min"])
            for row in rows
            if row.get("formal_confidence_min") is not None
        ]
        return {
            "status": status,
            "policy": "latest_per_topic",
            "totals": {
                "report_count": len(rows),
                "ready_count": int(status_counts.get("ready") or 0),
                "caution_count": int(status_counts.get("caution") or 0),
                "insufficient_count": int(status_counts.get("insufficient") or 0),
                "unknown_count": int(status_counts.get("unknown") or 0),
                "blocker_count": blocker_count,
                "warning_count": warning_count,
                "avg_formal_confidence_min": round(sum(confidence_values) / len(confidence_values), 2)
                if confidence_values
                else None,
            },
            "alerts": self._quality_summary_alerts(rows),
            "reports": rows,
        }

    def get_report(self, report_id: int) -> dict:
        with self.session_scope_factory() as session:
            report_repository = self.report_repository_cls(session)
            report = report_repository.get(report_id)
            if report is None:
                raise ReportQueryNotFound("report not found")
            run_repository = self.analysis_run_repository_cls(session)
            run = run_repository.get_by_report_id(report_id)
            run_payload = self.parse_run_payload_func(run.payload_json if run is not None else None)
            candidates = self.sanitize_candidates_func(self.candidate_audit_from_run_payload_func(run_payload))
            auto_follow_up = self.latest_follow_up_run_for_report_func(
                run_repository,
                report,
                report_repository,
            )
        promoted_tickers = self.report_tickers_func(report)
        markdown = self.remove_low_quality_lines_func(report.markdown)
        request = request_from_report_record(report.topic, promoted_tickers, run.payload_json if run is not None else None)
        parsed_quality_gate = _quality_gate_from_report(report, markdown, self.parse_quality_gate_func)
        quality_gate = self._refresh_quality_gate(request, parsed_quality_gate)
        if quality_gate:
            markdown = self._attach_quality_gate(markdown, report, quality_gate)
        return {
            "id": report.id,
            "title": report.title,
            "topic": report.topic,
            "tickers": promoted_tickers,
            "generated_at": report.generated_at.isoformat(),
            "markdown": self.sync_candidate_audit_func(markdown, candidates, promoted_tickers),
            "quality_gate": quality_gate,
            "request": request.model_dump(mode="json"),
            "workflow": run_payload.get("workflow") if isinstance(run_payload.get("workflow"), dict) else None,
            "auto_follow_up": auto_follow_up,
            "candidate_whitelist": candidates,
            "candidate_audit": {
                "summary": self.candidate_audit_summary_func(candidates, promoted_tickers),
                "markdown": self.render_candidate_audit_markdown_func(candidates, promoted_tickers)
                if candidates
                else "",
            },
        }

    def candidate_audit(self, report_id: int) -> dict:
        with self.session_scope_factory() as session:
            report = self.report_repository_cls(session).get(report_id)
            if report is None:
                raise ReportQueryNotFound("report not found")
            run = self.analysis_run_repository_cls(session).get_by_report_id(report_id)
            run_payload = self.parse_run_payload_func(run.payload_json if run is not None else None)
            candidates = self.sanitize_candidates_func(self.candidate_audit_from_run_payload_func(run_payload))
        promoted_tickers = self.report_tickers_func(report)
        return {
            "report_id": report_id,
            "promoted_tickers": promoted_tickers,
            "summary": self.candidate_audit_summary_func(candidates, promoted_tickers),
            "candidate_whitelist": candidates,
            "markdown": self.render_candidate_audit_markdown_func(candidates, promoted_tickers),
        }

    def _refresh_quality_gate(
        self,
        request: ReportRequest,
        parsed_quality_gate: dict | None,
    ) -> dict | None:
        if not isinstance(parsed_quality_gate, dict):
            return parsed_quality_gate
        metrics = parsed_quality_gate.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            return parsed_quality_gate
        try:
            return self.build_quality_gate_for_request_func(
                request,
                **_quality_gate_refresh_kwargs(metrics, len(request.tickers)),
            )
        except Exception:
            return parsed_quality_gate

    def _attach_quality_gate(self, markdown: str, report: Any, quality_gate: dict) -> str:
        response_payload: dict[str, Any] = {"title": getattr(report, "title", ""), "markdown": markdown}
        generated_at = getattr(report, "generated_at", None)
        if generated_at is not None:
            response_payload["generated_at"] = generated_at
        response = ReportResponse(**response_payload)
        return self.attach_quality_gate_to_report_func(response, quality_gate).markdown

    def _quality_summary_row(self, report: Any) -> dict:
        markdown = self.remove_low_quality_lines_func(str(getattr(report, "markdown", "") or ""))
        gate = _quality_gate_from_report(report, markdown, self.parse_quality_gate_func) or {}
        metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
        return {
            "id": getattr(report, "id", None),
            "title": getattr(report, "title", ""),
            "topic": getattr(report, "topic", ""),
            "generated_at": getattr(report, "generated_at", None).isoformat()
            if getattr(report, "generated_at", None) is not None
            else None,
            "status": str(gate.get("status") or "unknown"),
            "blocker_count": len(gate.get("blockers") or []),
            "warning_count": len(gate.get("warnings") or []),
            "observation_count": len(gate.get("observations") or []),
            "promoted_count": metrics.get("promoted_count"),
            "dynamic_source_count": metrics.get("dynamic_source_count"),
            "formal_confidence_min": metrics.get("formal_confidence_min"),
            "company_filing_coverage": metrics.get("company_filing_coverage"),
            "llm_estimated_cost_usd": metrics.get("llm_estimated_cost_usd"),
        }

    @staticmethod
    def _quality_summary_alerts(rows: list[dict]) -> list[dict[str, str]]:
        alerts = []
        for row in rows:
            if row.get("status") == "insufficient" or int(row.get("blocker_count") or 0):
                alerts.append(
                    {
                        "severity": "error",
                        "code": "report_quality_blocker",
                        "message": f"Report #{row.get('id')} has quality blockers.",
                    }
                )
            elif row.get("status") == "caution" or int(row.get("warning_count") or 0):
                alerts.append(
                    {
                        "severity": "warning",
                        "code": "report_quality_warning",
                        "message": f"Report #{row.get('id')} has quality warnings.",
                    }
                )
        return alerts[:10]

    def delete_report(self, report_id: int) -> dict:
        with self.session_scope_factory() as session:
            deleted = self.report_repository_cls(session).delete(report_id)
        if not deleted:
            raise ReportQueryNotFound("report not found")
        return {"deleted": True, "id": report_id}


def _count_values(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts
