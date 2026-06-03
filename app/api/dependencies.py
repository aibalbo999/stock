from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any

from fastapi import Request


SERVICE_FACTORY_DEPENDENCY_NAMES = (
    "asyncio",
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
    "report_execution_summary",
    "attach_quality_gate_to_report",
    "build_quality_gate_for_request",
    "build_report_quality_gate",
    "should_recover_market_data_quality",
    "parse_quality_gate_from_markdown",
    "summarize_document_source_quality",
    "summarize_llm_status",
    "ReportQueryService",
    "RunTaskApiService",
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
    "celery_app",
    "generate_report_task",
    "count_sufficient_company_filings",
    "load_report_follow_up_context",
    "prepare_follow_up_report_context",
    "refresh_market_data_for_report",
    "revalidate_candidate_whitelist",
    "get_report_follow_up_plan",
    "run_report_follow_up",
    "run_required_follow_up_background",
    "maybe_auto_start_required_follow_up",
    "safe_update_run_success",
    "safe_mark_run_failed",
    "discover_topic_with_timeout",
    "discovery_fetch_settings",
    "discovery_document_limit",
    "run_topic_discovery_ingestion",
    "should_revalidate_candidate_filings",
    "candidate_filing_revalidation_tickers",
    "company_filing_timeout_result",
    "dedupe_documents",
    "apply_company_filing_gate_to_candidate_payload",
    "summarize_candidate_support",
)


class ServiceFactoryDependencyNamespace(MutableMapping[str, Any]):
    def __init__(self, namespace: Mapping[str, Any], names: tuple[str, ...]) -> None:
        self.namespace = namespace
        self.names = tuple(dict.fromkeys(names))
        self.overrides: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        if key in self.overrides:
            return self.overrides[key]
        if key not in self.names:
            raise KeyError(key)
        return self.namespace[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self.names:
            self.names = (*self.names, key)
        self.overrides[key] = value

    def __delitem__(self, key: str) -> None:
        if key in self.overrides:
            del self.overrides[key]
            return
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.names)

    def __len__(self) -> int:
        return len(self.names)


def build_service_factory_dependencies(namespace: Mapping[str, Any]) -> ServiceFactoryDependencyNamespace:
    missing = [name for name in SERVICE_FACTORY_DEPENDENCY_NAMES if name not in namespace]
    if missing:
        raise RuntimeError(
            "API service factory dependency namespace is missing: "
            + ", ".join(sorted(missing))
        )
    return ServiceFactoryDependencyNamespace(namespace, SERVICE_FACTORY_DEPENDENCY_NAMES)


def get_api_services(request: Request) -> Any:
    return request.app.state.api_services


def api_services_provider(static_api_services: Any | None = None):
    if static_api_services is not None:
        return lambda: static_api_services
    return get_api_services
