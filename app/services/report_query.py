from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from app.core.config import get_settings
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
from app.services.report_files import REPORT_ARTIFACT_SUFFIXES
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
        settings_provider: Callable[[], Any] = get_settings,
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
        self.settings_provider = settings_provider

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

    def observability_summary(self, limit: int = 20) -> dict:
        safe_limit = max(1, min(int(limit or 20), 100))
        snapshots = []
        with self.session_scope_factory() as session:
            report_repository = self.report_repository_cls(session)
            run_repository = self.analysis_run_repository_cls(session)
            latest_by_topic = getattr(report_repository, "latest_by_topic", None)
            reports = (
                latest_by_topic(safe_limit)
                if callable(latest_by_topic)
                else report_repository.latest(safe_limit)
            )
            for report in reports:
                run = run_repository.get_by_report_id(getattr(report, "id", 0))
                snapshots.append(
                    {
                        "id": getattr(report, "id", None),
                        "title": getattr(report, "title", ""),
                        "topic": getattr(report, "topic", ""),
                        "generated_at": getattr(report, "generated_at", None).isoformat()
                        if getattr(report, "generated_at", None) is not None
                        else None,
                        "run_id": getattr(run, "id", None) if run is not None else None,
                        "run_source": getattr(run, "source", None) if run is not None else None,
                        "run_status": getattr(run, "status", None) if run is not None else None,
                        "run_started_at": getattr(run, "started_at", None).isoformat()
                        if run is not None and getattr(run, "started_at", None) is not None
                        else None,
                        "run_finished_at": getattr(run, "finished_at", None).isoformat()
                        if run is not None and getattr(run, "finished_at", None) is not None
                        else None,
                        "run_payload": getattr(run, "payload_json", None) if run is not None else None,
                    }
                )
        rows = [self._observability_summary_row(snapshot) for snapshot in snapshots]
        totals = _observability_totals(rows)
        bottlenecks = _observability_bottleneck_rows(rows)
        totals["bottleneck_count"] = len(bottlenecks)
        totals["highest_bottleneck_score"] = (
            bottlenecks[0]["score"] if bottlenecks else 0.0
        )
        status = _observability_status(rows, totals)
        return {
            "status": status,
            "policy": "latest_per_topic",
            "totals": totals,
            "alerts": self._observability_alerts(rows, totals),
            "bottlenecks": bottlenecks,
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

    def _observability_summary_row(self, snapshot: dict[str, Any]) -> dict:
        payload = self.parse_run_payload_func(snapshot.get("run_payload"))
        execution = _report_execution_from_payload(payload)
        llm = execution.get("llm") if isinstance(execution.get("llm"), dict) else {}
        llm_observability = (
            llm.get("observability")
            if isinstance(llm.get("observability"), dict)
            else {}
        )
        attempt_summary = (
            llm.get("attempt_summary")
            if isinstance(llm.get("attempt_summary"), dict)
            else {}
        )
        routing_decision = (
            llm_observability.get("routing_decision")
            if isinstance(llm_observability.get("routing_decision"), dict)
            else {}
        )
        retrieval_trace = (
            execution.get("retrieval_trace")
            if isinstance(execution.get("retrieval_trace"), dict)
            else {}
        )
        reranker_status = (
            retrieval_trace.get("reranker_status")
            if isinstance(retrieval_trace.get("reranker_status"), dict)
            else {}
        )
        graph_reasoning = (
            execution.get("graph_reasoning")
            if isinstance(execution.get("graph_reasoning"), dict)
            else {}
        )
        return {
            "id": snapshot.get("id"),
            "title": snapshot.get("title"),
            "topic": snapshot.get("topic"),
            "generated_at": snapshot.get("generated_at"),
            "run_id": snapshot.get("run_id"),
            "run_source": snapshot.get("run_source"),
            "run_status": snapshot.get("run_status"),
            "model": llm.get("model"),
            "provider": llm.get("provider"),
            "fallback": bool(llm.get("fallback")),
            "fallback_path_used": bool(attempt_summary.get("fallback_path_used")),
            "attempt_count": _metric_int(attempt_summary.get("attempt_count")),
            "retryable_failure_count": _metric_int(
                attempt_summary.get("retryable_failure_count"),
                default=0,
            ),
            "primary_failure_category": attempt_summary.get("primary_failure_category"),
            "llm_latency_ms": _metric_float(llm_observability.get("latency_ms")),
            "total_token_estimate": _metric_int(llm_observability.get("total_token_estimate")),
            "estimated_cost_usd": _metric_float(llm_observability.get("estimated_cost_usd")),
            "cost_tracking_mode": llm_observability.get("cost_tracking_mode"),
            "selected_model_rank": _metric_int(
                llm_observability.get("selected_model_rank")
                if llm_observability.get("selected_model_rank") is not None
                else routing_decision.get("selected_model_rank")
            ),
            "selected_routing_tier": (
                llm_observability.get("selected_routing_tier")
                or routing_decision.get("selected_routing_tier")
            ),
            "routing_reason": routing_decision.get("routing_reason"),
            "quota_skip_count": _metric_int(
                llm_observability.get("quota_skip_count")
                if llm_observability.get("quota_skip_count") is not None
                else routing_decision.get("quota_skip_count"),
                default=0,
            ),
            "daily_quota_skip_count": _metric_int(
                llm_observability.get("daily_quota_skip_count")
                if llm_observability.get("daily_quota_skip_count") is not None
                else routing_decision.get("daily_quota_skip_count"),
                default=0,
            ),
            "cooldown_skip_count": _metric_int(
                llm_observability.get("cooldown_skip_count")
                if llm_observability.get("cooldown_skip_count") is not None
                else routing_decision.get("cooldown_skip_count"),
                default=0,
            ),
            "degraded_from_primary": bool(
                llm_observability.get("degraded_from_primary")
                if llm_observability.get("degraded_from_primary") is not None
                else routing_decision.get("degraded_from_primary")
            ),
            "retrieval_strategy": retrieval_trace.get("strategy"),
            "retrieval_latency_ms": _metric_float(
                retrieval_trace.get("duration_ms")
                if retrieval_trace.get("duration_ms") is not None
                else llm_observability.get("retrieval_latency_ms")
            ),
            "retrieval_candidate_count": _metric_int(retrieval_trace.get("candidate_count")),
            "retrieval_returned_count": _metric_int(retrieval_trace.get("returned_count")),
            "reranker_provider": (
                reranker_status.get("resolved_provider")
                or reranker_status.get("normalized_provider")
                or reranker_status.get("provider")
            ),
            "reranker_execution_mode": reranker_status.get("execution_mode"),
            "reranker_quality_tier": reranker_status.get("quality_tier"),
            "model_reranker_ready": bool(reranker_status.get("model_reranker_ready")),
            "keyword_fallback": bool(reranker_status.get("keyword_fallback")),
            "reranker_fallback_reason": (
                reranker_status.get("fallback_reason")
                or reranker_status.get("model_reranker_gap")
            ),
            "graph_reasoning_status": graph_reasoning.get("status"),
            "graph_reasoning_strategy": graph_reasoning.get("strategy"),
            "graph_reasoning_max_paths": graph_reasoning.get("max_paths"),
            "trace_captured": bool(llm_observability or retrieval_trace or graph_reasoning),
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

    @staticmethod
    def _observability_alerts(rows: list[dict], totals: dict[str, Any]) -> list[dict[str, str]]:
        alerts = []
        if rows and int(totals.get("trace_missing_count") or 0):
            alerts.append(
                {
                    "severity": "warning",
                    "code": "report_trace_missing",
                    "message": "Some latest reports do not have stored LLM/RAG trace payloads.",
                }
            )
        if int(totals.get("fallback_path_count") or 0):
            alerts.append(
                {
                    "severity": "warning",
                    "code": "report_llm_fallback_used",
                    "message": "Some latest reports used LLM fallback routing.",
                }
            )
        if int(totals.get("retryable_failure_count") or 0):
            alerts.append(
                {
                    "severity": "warning",
                    "code": "report_llm_retryable_failures",
                    "message": "Retryable LLM failures were observed during latest report generation.",
                }
            )
        if int(totals.get("keyword_fallback_count") or 0):
            alerts.append(
                {
                    "severity": "info",
                    "code": "report_reranker_keyword_fallback",
                    "message": "Some latest reports used keyword reranking instead of a model/API reranker.",
                }
            )
        return alerts[:10]

    def delete_report(self, report_id: int) -> dict:
        output_paths: list[str] = []
        with self.session_scope_factory() as session:
            run_repository = self.analysis_run_repository_cls(session)
            output_paths_for_report = getattr(run_repository, "output_paths_for_report", None)
            if callable(output_paths_for_report):
                output_paths = output_paths_for_report(report_id)
            else:
                run = run_repository.get_by_report_id(report_id)
                output_path = getattr(run, "output_path", None) if run is not None else None
                output_paths = [str(output_path)] if output_path else []
            deleted = self.report_repository_cls(session).delete(report_id)
        if not deleted:
            raise ReportQueryNotFound("report not found")
        return {
            "deleted": True,
            "id": report_id,
            "deleted_report_files": delete_report_markdown_files(
                output_paths,
                report_dir=Path(getattr(self.settings_provider(), "report_dir", Path("reports"))),
            ),
        }


def delete_report_markdown_files(output_paths: list[str], *, report_dir: Path) -> int:
    deleted = 0
    seen: set[Path] = set()
    root = _resolved_report_dir(report_dir)
    for output_path in output_paths:
        candidate = _safe_report_markdown_path(output_path, root)
        if candidate is None:
            continue
        for artifact in _report_artifact_sibling_paths(candidate, root):
            if artifact in seen:
                continue
            seen.add(artifact)
            try:
                artifact.unlink()
                deleted += 1
            except FileNotFoundError:
                continue
            except OSError:
                continue
    return deleted


def _safe_report_markdown_path(output_path: str, report_dir: Path) -> Path | None:
    if not str(output_path or "").strip():
        return None
    candidate = Path(output_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if resolved.suffix.lower() != ".md" or not resolved.is_file():
        return None
    if resolved != report_dir and report_dir not in resolved.parents:
        return None
    return resolved


def _report_artifact_sibling_paths(markdown_path: Path, report_dir: Path) -> list[Path]:
    artifacts = []
    for suffix in sorted(REPORT_ARTIFACT_SUFFIXES):
        candidate = markdown_path.with_suffix(suffix)
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved != report_dir and report_dir not in resolved.parents:
            continue
        if resolved.is_file():
            artifacts.append(resolved)
    return artifacts


def _resolved_report_dir(report_dir: Path) -> Path:
    root = report_dir.expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def _count_values(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _report_execution_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("report_execution")
    if isinstance(direct, dict):
        return direct
    for key in ("rerun_report", "report_result"):
        nested = payload.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("report_execution"), dict):
            return nested["report_execution"]
    return {}


def _observability_totals(rows: list[dict]) -> dict[str, Any]:
    latency_values = [row["llm_latency_ms"] for row in rows if row.get("llm_latency_ms") is not None]
    retrieval_latency_values = [
        row["retrieval_latency_ms"]
        for row in rows
        if row.get("retrieval_latency_ms") is not None
    ]
    return {
        "report_count": len(rows),
        "trace_captured_count": sum(1 for row in rows if row.get("trace_captured")),
        "trace_missing_count": sum(1 for row in rows if not row.get("trace_captured")),
        "total_token_estimate": sum(row.get("total_token_estimate") or 0 for row in rows),
        "estimated_cost_usd": round(sum(row.get("estimated_cost_usd") or 0.0 for row in rows), 6),
        "fallback_count": sum(1 for row in rows if row.get("fallback")),
        "fallback_path_count": sum(1 for row in rows if row.get("fallback_path_used")),
        "retryable_failure_count": sum(row.get("retryable_failure_count") or 0 for row in rows),
        "quota_skip_count": sum(row.get("quota_skip_count") or 0 for row in rows),
        "daily_quota_skip_count": sum(row.get("daily_quota_skip_count") or 0 for row in rows),
        "cooldown_skip_count": sum(row.get("cooldown_skip_count") or 0 for row in rows),
        "degraded_from_primary_count": sum(1 for row in rows if row.get("degraded_from_primary")),
        "retrieval_trace_count": sum(1 for row in rows if row.get("retrieval_strategy")),
        "model_reranker_ready_count": sum(1 for row in rows if row.get("model_reranker_ready")),
        "keyword_fallback_count": sum(1 for row in rows if row.get("keyword_fallback")),
        "graph_reasoning_ready_count": sum(
            1 for row in rows if row.get("graph_reasoning_status") == "ready"
        ),
        "avg_llm_latency_ms": round(sum(latency_values) / len(latency_values), 2)
        if latency_values
        else None,
        "avg_retrieval_latency_ms": round(
            sum(retrieval_latency_values) / len(retrieval_latency_values),
            2,
        )
        if retrieval_latency_values
        else None,
    }


def _observability_bottleneck_rows(rows: list[dict], limit: int = 10) -> list[dict[str, Any]]:
    bottlenecks = [
        row
        for row in (
            _observability_bottleneck_row(report_row) for report_row in rows
        )
        if row is not None
    ]
    return sorted(
        bottlenecks,
        key=lambda item: (-float(item["score"]), str(item.get("generated_at") or ""), int(item.get("id") or 0)),
    )[: max(1, min(int(limit or 10), 25))]


def _observability_bottleneck_row(row: dict) -> dict[str, Any] | None:
    components = _observability_bottleneck_components(row)
    if not components:
        return None
    dominant_factor = max(components, key=components.get)
    reasons = _observability_bottleneck_reasons(row)
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "topic": row.get("topic"),
        "generated_at": row.get("generated_at"),
        "score": round(sum(components.values()), 2),
        "dominant_factor": dominant_factor,
        "severity": _observability_bottleneck_severity(row, dominant_factor),
        "next_action": _observability_bottleneck_next_action(row, dominant_factor),
        "reasons": "；".join(reasons),
        "model": row.get("model"),
        "llm_latency_ms": row.get("llm_latency_ms"),
        "retrieval_latency_ms": row.get("retrieval_latency_ms"),
        "total_token_estimate": row.get("total_token_estimate"),
        "estimated_cost_usd": row.get("estimated_cost_usd"),
    }


def _observability_bottleneck_components(row: dict) -> dict[str, float]:
    components: dict[str, float] = {}
    if not row.get("trace_captured"):
        components["trace_missing"] = 80.0
    if row.get("fallback_path_used"):
        components["llm_fallback"] = 40.0
    retryable_failures = _metric_int(row.get("retryable_failure_count"), default=0) or 0
    if retryable_failures:
        components["retryable_failures"] = min(30.0, float(retryable_failures) * 10.0)
    quota_skips = _metric_int(row.get("quota_skip_count"), default=0) or 0
    if quota_skips:
        components["quota_routing_skip"] = min(15.0, float(quota_skips) * 5.0)
    if row.get("keyword_fallback"):
        components["keyword_reranker_fallback"] = 12.0
    llm_latency_ms = _metric_float(row.get("llm_latency_ms"))
    if llm_latency_ms is not None and llm_latency_ms > 0:
        components["llm_latency"] = min(35.0, llm_latency_ms / 1000.0)
    retrieval_latency_ms = _metric_float(row.get("retrieval_latency_ms"))
    if retrieval_latency_ms is not None and retrieval_latency_ms > 0:
        components["retrieval_latency"] = min(20.0, retrieval_latency_ms / 100.0)
    total_tokens = _metric_int(row.get("total_token_estimate"), default=0) or 0
    if total_tokens:
        components["token_volume"] = min(25.0, total_tokens / 2000.0)
    estimated_cost = _metric_float(row.get("estimated_cost_usd"), default=0.0) or 0.0
    if estimated_cost:
        components["estimated_cost"] = min(30.0, estimated_cost * 1000.0)
    return components


def _observability_bottleneck_reasons(row: dict) -> list[str]:
    reasons: list[str] = []
    if not row.get("trace_captured"):
        reasons.append("trace_missing")
    if row.get("fallback_path_used"):
        reasons.append("llm_fallback")
    retryable_failures = _metric_int(row.get("retryable_failure_count"), default=0) or 0
    if retryable_failures:
        reasons.append(f"retryable_failures={retryable_failures}")
    quota_skips = _metric_int(row.get("quota_skip_count"), default=0) or 0
    if quota_skips:
        reasons.append(f"quota_skips={quota_skips}")
    if row.get("routing_reason"):
        reasons.append(f"routing_reason={row['routing_reason']}")
    if row.get("keyword_fallback"):
        reasons.append("keyword_reranker_fallback")
    if row.get("llm_latency_ms") is not None:
        reasons.append(f"llm_latency_ms={row['llm_latency_ms']}")
    if row.get("retrieval_latency_ms") is not None:
        reasons.append(f"retrieval_latency_ms={row['retrieval_latency_ms']}")
    if row.get("total_token_estimate"):
        reasons.append(f"tokens={row['total_token_estimate']}")
    if row.get("estimated_cost_usd"):
        reasons.append(f"cost_usd={row['estimated_cost_usd']}")
    return reasons


def _observability_bottleneck_severity(row: dict, dominant_factor: str) -> str:
    if dominant_factor == "trace_missing":
        return "warning"
    if row.get("fallback_path_used") or _metric_int(row.get("retryable_failure_count"), default=0):
        return "warning"
    return "info"


def _observability_bottleneck_next_action(row: dict, dominant_factor: str) -> str:
    if dominant_factor == "trace_missing":
        return "重新產生或檢查 run payload 是否寫入 report_execution trace。"
    if dominant_factor in {"llm_fallback", "retryable_failures"}:
        return "檢查 quota/routing、429 cooldown 與模型順序，避免每份報告先撞耗盡模型。"
    if dominant_factor == "quota_routing_skip":
        return "檢查今日模型額度與 cooldown；若為預期降級，確認高額度 fallback 排在聰明模型之後。"
    if dominant_factor == "keyword_reranker_fallback":
        return "啟用 cross-encoder、Cohere 或 LLM reranker，降低關鍵字 fallback 排序風險。"
    if dominant_factor == "retrieval_latency":
        return "檢查 vector store 查詢、hybrid candidate 數量與 rerank top-k。"
    if dominant_factor == "token_volume":
        return "壓縮 prompt、RAG context 或報告章節輸入，降低免費額度消耗。"
    if dominant_factor == "estimated_cost":
        return "確認 rate card、模型路由與是否可用 Flash-Lite/Gemma 承接低風險任務。"
    return "檢查 LLM latency、prompt 長度與模型 fallback 設定。"


def _observability_status(rows: list[dict], totals: dict[str, Any]) -> str:
    if not rows:
        return "no_reports"
    if int(totals.get("trace_missing_count") or 0):
        return "caution"
    if int(totals.get("fallback_path_count") or 0) or int(totals.get("retryable_failure_count") or 0):
        return "caution"
    return "ready"


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
