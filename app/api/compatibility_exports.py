from __future__ import annotations

# ruff: noqa: F401

import asyncio
from datetime import date

from app.api.schemas import (
    FollowUpRunRequest,
    TopicDiscoveryRequest,
)
from app.core.config import get_settings
from app.core.time import today_taipei
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    filing_quality_score,
    filing_source_tier,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest
from app.rag.vector_store import VectorStore
from app.services import candidate_revalidation
from app.services.candidate_audit import (
    candidate_audit_summary,
    render_candidate_audit_markdown,
)
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.company_data_audit import audit_company_data, audit_report_company_data
from app.services.company_data_audit_api import CompanyDataAuditApiNotFound, CompanyDataAuditApiService
from app.services.company_filing_api import CompanyFilingApiService
from app.services.data_operations_api import DataOperationsApiService
from app.services.discovery_api import DiscoveryApiService
from app.services.discovery_workflow import (
    DiscoveryWorkflowService,
    build_source_audit,
    discovery_analysis_mode,
    discovery_document_limit,
    discovery_effective_lookback_days,
    discovery_fetch_settings,
    discovery_market_history_days,
    discovery_query_budget,
    discovery_valuation_history_days,
    escalate_discovery_budget,
    is_deep_discovery,
    query_intent_label,
    query_type_label,
    should_escalate_discovery_budget,
    should_supplement_discovery_sources,
    source_selection_context,
    summarize_candidate_support,
    summarize_ingestion_stage,
    summarize_source_categories,
    summarize_source_intents,
    summarize_source_selection,
)
from app.services.discovered_market_data import (
    DiscoveredMarketDataService,
    market_timeout_errors,
    merge_financial_metric_history,
    merge_latest_by_ticker,
)
from app.services.discovered_candidate_filings import (
    candidate_filing_revalidation_tickers,
    company_filing_timeout_result,
    should_revalidate_candidate_filings,
)
from app.services.discovered_pipeline import DiscoveredTopicPipelineService
from app.services.discovered_report_builder import DiscoveredReportBuilderService
from app.services.entity_mapping import EntityMapper
from app.services.followup_actions import (
    FollowUpActionPlanner,
    TRACKING_FRESHNESS_THRESHOLDS,
    execute_follow_up_actions,
    render_follow_up_actions_markdown,
    split_fresh_tracking_actions,
    summarize_follow_up_execution,
)
from app.services.ingestion import IngestionPipeline
from app.services.llm_api import LLMApiService
from app.services.llm_client import LLMClient
from app.services.persistence import (
    AnalysisRunRepository,
    CompanyFilingRepository,
    FinancialMetricRepository,
    LLMUsageRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    NewsRepository,
    ReportRepository,
    ValuationMetricRepository,
)
from app.services.pipeline_api import PipelineApiService
from app.services.report_build import ReportBuildService
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
from app.services.report_execution import report_execution_summary
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
from app.services.run_state import RunStateService
from app.services.run_task_api import (
    AsyncReportValidationError,
    RunTaskApiService,
    RunTaskNotFound,
    TaskQueueUnavailableError,
)
from app.services.schedule_config import ScheduleConfigStore
from app.services.source_quality import filter_formal_evidence_documents, remove_low_quality_investor_forum_lines
from app.services.source_relevance import SourceRelevanceAnalyzer
from app.services.standard_pipeline import StandardReportPipelineService
from app.services.supply_chain_graph_api import SupplyChainGraphApiService
from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.topic_discovery import TopicDiscoveryPlan, TopicDiscoveryService
from app.services.whitelist import SupplyChainWhitelist
from app.services.workflow_checkpoint import (
    DISCOVERED_PIPELINE_STEPS,
    STANDARD_PIPELINE_STEPS,
    WorkflowCheckpointRecorder,
)
from app.services.workflow_orchestration import WorkflowOrchestrationError, WorkflowOrchestrationRunner


LEGACY_HELPER_EXPORT_NAMES = (
    "build_source_audit",
    "candidate_filing_revalidation_tickers",
    "company_filing_timeout_result",
    "discovery_analysis_mode",
    "discovery_document_limit",
    "discovery_effective_lookback_days",
    "discovery_fetch_settings",
    "discovery_market_history_days",
    "discovery_query_budget",
    "discovery_valuation_history_days",
    "escalate_discovery_budget",
    "is_deep_discovery",
    "market_timeout_errors",
    "merge_financial_metric_history",
    "merge_latest_by_ticker",
    "query_intent_label",
    "query_type_label",
    "should_escalate_discovery_budget",
    "should_revalidate_candidate_filings",
    "should_supplement_discovery_sources",
    "source_selection_context",
    "summarize_candidate_support",
    "summarize_ingestion_stage",
    "summarize_source_categories",
    "summarize_source_intents",
    "summarize_source_selection",
)


COMPATIBILITY_EXPORT_NAMES = tuple(
    dict.fromkeys(
        (
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
    )
)


def compatibility_export_namespace() -> dict[str, object]:
    return {name: globals()[name] for name in COMPATIBILITY_EXPORT_NAMES}
