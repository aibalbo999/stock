from __future__ import annotations

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
from app.services.report_quality import parse_quality_gate_from_markdown
from app.services.source_quality import remove_low_quality_investor_forum_lines


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
        self.candidate_audit_summary_func = candidate_audit_summary_func
        self.render_candidate_audit_markdown_func = render_candidate_audit_markdown_func
        self.report_tickers_func = report_tickers_func

    def list_reports(self, limit: int = 20) -> list[dict]:
        with self.session_scope_factory() as session:
            reports = self.report_repository_cls(session).latest(limit)
        return [
            {
                "id": report.id,
                "title": report.title,
                "topic": report.topic,
                "generated_at": report.generated_at.isoformat(),
            }
            for report in reports
        ]

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
        return {
            "id": report.id,
            "title": report.title,
            "topic": report.topic,
            "tickers": promoted_tickers,
            "generated_at": report.generated_at.isoformat(),
            "markdown": self.sync_candidate_audit_func(markdown, candidates, promoted_tickers),
            "quality_gate": self.parse_quality_gate_func(markdown),
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

    def delete_report(self, report_id: int) -> dict:
        with self.session_scope_factory() as session:
            deleted = self.report_repository_cls(session).delete(report_id)
        if not deleted:
            raise ReportQueryNotFound("report not found")
        return {"deleted": True, "id": report_id}
