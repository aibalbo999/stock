from __future__ import annotations

# ruff: noqa: F401

from app.models.schemas import ReportRequest
from app.services.followup_actions import (
    FollowUpActionPlanner,
    TRACKING_FRESHNESS_THRESHOLDS,
    execute_follow_up_actions,
    render_follow_up_actions_markdown,
    split_fresh_tracking_actions,
    summarize_follow_up_execution,
)
from app.services.report_build import ReportBuildService
from app.services.report_execution import report_execution_summary
from app.services.report_followup import (
    append_candidate_audit_if_missing,
    candidate_audit_from_run_payload,
    follow_up_action_summary,
    follow_up_plan_next_actions,
    latest_follow_up_run_for_report,
    parse_run_payload,
    serialize_run,
    should_require_candidate_audit_follow_up,
    summarize_candidate_support_payload,
)
from app.services.report_followup_context import ReportFollowUpContextService
from app.services.report_followup_plan import AutoFollowUpStartService, ReportFollowUpPlanService
from app.services.report_followup_runner import ReportFollowUpRunService
from app.services.report_generation_api import SyncReportGenerationApiService
from app.services.report_generator import ReportExecutionError, ReportGenerator
from app.services.report_quality import (
    attach_quality_gate_to_report,
    build_quality_gate_for_request,
    build_report_quality_gate,
    parse_quality_gate_from_markdown,
    should_recover_market_data_quality,
    summarize_document_source_quality,
    summarize_llm_status,
)
from app.services.report_query import ReportQueryNotFound, ReportQueryService

REPORT_EXPORT_NAMES = (
    "FollowUpActionPlanner",
    "TRACKING_FRESHNESS_THRESHOLDS",
    "execute_follow_up_actions",
    "render_follow_up_actions_markdown",
    "split_fresh_tracking_actions",
    "summarize_follow_up_execution",
    "ReportBuildService",
    "ReportRequest",
    "append_candidate_audit_if_missing",
    "candidate_audit_from_run_payload",
    "follow_up_action_summary",
    "follow_up_plan_next_actions",
    "latest_follow_up_run_for_report",
    "parse_run_payload",
    "serialize_run",
    "should_require_candidate_audit_follow_up",
    "summarize_candidate_support_payload",
    "ReportFollowUpContextService",
    "AutoFollowUpStartService",
    "ReportFollowUpPlanService",
    "ReportFollowUpRunService",
    "SyncReportGenerationApiService",
    "ReportGenerator",
    "ReportExecutionError",
    "report_execution_summary",
    "attach_quality_gate_to_report",
    "build_quality_gate_for_request",
    "build_report_quality_gate",
    "should_recover_market_data_quality",
    "parse_quality_gate_from_markdown",
    "summarize_document_source_quality",
    "summarize_llm_status",
    "ReportQueryService",
    "ReportQueryNotFound",
)


def compatibility_report_export_namespace() -> dict[str, object]:
    return {name: globals()[name] for name in REPORT_EXPORT_NAMES}
