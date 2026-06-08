from __future__ import annotations

from collections.abc import Callable

from app.api.compatibility_export_core import (
    CORE_EXPORT_NAMES,
    compatibility_core_export_namespace,
)
from app.api.compatibility_export_data import (
    DATA_EXPORT_NAMES,
    compatibility_data_export_namespace,
)
from app.api.compatibility_export_discovery import (
    DISCOVERY_EXPORT_NAMES,
    DISCOVERY_LEGACY_HELPER_EXPORT_NAMES,
    compatibility_discovery_export_namespace,
)
from app.api.compatibility_export_report import (
    REPORT_EXPORT_NAMES,
    compatibility_report_export_namespace,
)
from app.api.compatibility_export_workflow import (
    WORKFLOW_EXPORT_NAMES,
    compatibility_workflow_export_namespace,
)

LEGACY_HELPER_EXPORT_NAMES = DISCOVERY_LEGACY_HELPER_EXPORT_NAMES

COMPATIBILITY_EXPORT_NAMES = (
    "asyncio",
    "date",
    "candidate_revalidation",
    "init_db",
    "get_settings",
    "today_taipei",
    "session_scope",
    "CompanyFilingFetcher",
    "filing_quality_score",
    "filing_source_tier",
    "FollowUpRunRequest",
    "MarketDataClient",
    "NewsFetcher",
    "NewsSourceStore",
    "VectorStore",
    "candidate_audit_summary",
    "render_candidate_audit_markdown",
    "audit_company_data",
    "audit_report_company_data",
    "CompanyDataAuditApiService",
    "CompanyDataAuditApiNotFound",
    "CompanyFilingApiService",
    "DataOperationsApiService",
    "CandidateRevalidationService",
    "DiscoveryApiService",
    "DiscoveredMarketDataService",
    "DiscoveredTopicPipelineService",
    "DiscoveredReportBuilderService",
    "DiscoveryWorkflowService",
    "EntityMapper",
    "FollowUpActionPlanner",
    "TRACKING_FRESHNESS_THRESHOLDS",
    "execute_follow_up_actions",
    "render_follow_up_actions_markdown",
    "split_fresh_tracking_actions",
    "summarize_follow_up_execution",
    "IngestionPipeline",
    "AnalysisRunRepository",
    "CompanyFilingRepository",
    "FinancialMetricRepository",
    "LLMUsageRepository",
    "MarketRepository",
    "MonthlyRevenueRepository",
    "NewsRepository",
    "ReportRepository",
    "ValuationMetricRepository",
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
    "RunTaskApiService",
    "AsyncReportValidationError",
    "RunTaskNotFound",
    "TaskQueueUnavailableError",
    "RunStateService",
    "LLMApiService",
    "LLMClient",
    "PipelineApiService",
    "ScheduleConfigStore",
    "filter_formal_evidence_documents",
    "remove_low_quality_investor_forum_lines",
    "SourceRelevanceAnalyzer",
    "StandardReportPipelineService",
    "SupplyChainGraphApiService",
    "Neo4jGraphImportService",
    "TopicDiscoveryPlan",
    "TopicDiscoveryRequest",
    "TopicDiscoveryService",
    "SupplyChainWhitelist",
    "DISCOVERED_PIPELINE_STEPS",
    "STANDARD_PIPELINE_STEPS",
    "WorkflowCheckpointRecorder",
    "WorkflowOrchestrationError",
    "WorkflowOrchestrationRunner",
    *LEGACY_HELPER_EXPORT_NAMES,
)

_DOMAIN_EXPORT_NAMES = (
    *CORE_EXPORT_NAMES,
    *DATA_EXPORT_NAMES,
    *DISCOVERY_EXPORT_NAMES,
    *REPORT_EXPORT_NAMES,
    *WORKFLOW_EXPORT_NAMES,
)
_MISSING_DOMAIN_EXPORT_NAMES = tuple(
    name for name in COMPATIBILITY_EXPORT_NAMES if name not in _DOMAIN_EXPORT_NAMES
)
if _MISSING_DOMAIN_EXPORT_NAMES:
    raise RuntimeError(
        "Compatibility export names are missing from domain builders: "
        + ", ".join(_MISSING_DOMAIN_EXPORT_NAMES)
    )

_COMPATIBILITY_EXPORT_NAMESPACE_BUILDERS: tuple[Callable[[], dict[str, object]], ...] = (
    compatibility_core_export_namespace,
    compatibility_data_export_namespace,
    compatibility_discovery_export_namespace,
    compatibility_report_export_namespace,
    compatibility_workflow_export_namespace,
)


def compatibility_export_namespace() -> dict[str, object]:
    namespace: dict[str, object] = {}
    for build_namespace in _COMPATIBILITY_EXPORT_NAMESPACE_BUILDERS:
        namespace.update(build_namespace())
    return {name: namespace[name] for name in COMPATIBILITY_EXPORT_NAMES}


globals().update(compatibility_export_namespace())
