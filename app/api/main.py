from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import FastAPI

from app.api.ai_routes import create_ai_router
from app.api.company_filing_routes import create_company_filing_router
from app.api.legacy_facade import LegacyApiFacade
from app.api.operations_routes import create_operations_router
from app.api.pipeline_routes import create_pipeline_router
from app.api.report_routes import create_report_router
from app.api.service_factory import ApiServiceFactory
from app.api.supply_chain_routes import create_supply_chain_router
from app.api.system_routes import create_system_router
from app.core.config import get_settings
from app.core.time import today_taipei
from app.api.schemas import (
    FollowUpRunRequest,
    TopicDiscoveryRequest,
)
from app.data_sources.company_filings import (
    CompanyFilingFetcher,
    filing_quality_score,
    filing_source_tier,
)
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher, NewsSourceStore
from app.db.status import db_status
from app.db.session import init_db, session_scope
from app.models.schemas import ReportRequest
from app.rag.vector_store import VectorStore
from app.services.candidate_audit import (
    candidate_audit_summary,
    render_candidate_audit_markdown,
)
from app.services.company_data_audit import audit_company_data, audit_report_company_data
from app.services.company_data_audit_api import CompanyDataAuditApiNotFound, CompanyDataAuditApiService
from app.services.company_filing_api import CompanyFilingApiService
from app.services.data_operations_api import DataOperationsApiService
from app.services import candidate_revalidation
from app.services.candidate_revalidation import CandidateRevalidationService
from app.services.discovery_api import DiscoveryApiService
from app.services.discovered_market_data import (
    DiscoveredMarketDataService,
    market_timeout_errors,
    merge_financial_metric_history,
    merge_latest_by_ticker,
)
from app.services.discovered_pipeline import (
    DiscoveredTopicPipelineService,
    candidate_filing_revalidation_tickers,
    company_filing_timeout_result,
    should_revalidate_candidate_filings,
)
from app.services.discovered_report_builder import DiscoveredReportBuilderService
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
from app.services.entity_mapping import EntityMapper
from app.services.followup_actions import (
    FollowUpActionPlanner,
    TRACKING_FRESHNESS_THRESHOLDS,
    execute_follow_up_actions,
    render_follow_up_actions_markdown,
    split_fresh_tracking_actions,
    summarize_follow_up_execution,
)
from app.services.ingestion import (
    IngestionPipeline,
)
from app.services.persistence import (
    AnalysisRunRepository,
    CompanyFilingRepository,
    FinancialMetricRepository,
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
from app.services.report_generator import ReportExecutionError, ReportGenerator, report_execution_summary
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
from app.services.run_task_api import AsyncReportValidationError, RunTaskApiService, RunTaskNotFound
from app.services.run_state import RunStateService
from app.services.llm_api import LLMApiService
from app.services.llm_client import LLMClient
from app.services.schedule_config import ScheduleConfigStore
from app.services.service_status import service_status
from app.services.source_quality import filter_formal_evidence_documents, remove_low_quality_investor_forum_lines
from app.services.source_relevance import SourceRelevanceAnalyzer
from app.services.standard_pipeline import StandardReportPipelineService
from app.services.supply_chain_graph_api import SupplyChainGraphApiService
from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.topic_discovery import TopicDiscoveryPlan, TopicDiscoveryService
from app.services.upgrade_audit import audit_upgrade_capabilities
from app.services.whitelist import SupplyChainWhitelist
from app.services.workflow_checkpoint import (
    DISCOVERED_PIPELINE_STEPS,
    STANDARD_PIPELINE_STEPS,
    WorkflowCheckpointRecorder,
)
from app.services.workflow_orchestration import WorkflowOrchestrationError, WorkflowOrchestrationRunner
from app.tasks.celery_app import celery_app
from app.tasks.tasks import generate_report_task


LOGGER = logging.getLogger(__name__)

__all__ = [
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
]


def sufficient_company_filing_tickers(tickers: list[str]) -> set[str]:
    return _legacy_api.sufficient_company_filing_tickers(tickers)


def count_sufficient_company_filings(tickers: list[str]) -> int:
    return _legacy_api.count_sufficient_company_filings(tickers)


def apply_company_filing_gate_to_candidate_payload(candidates: list[dict]) -> list[dict]:
    return _legacy_api.apply_company_filing_gate_to_candidate_payload(
        candidates,
        sufficient_tickers_provider=sufficient_company_filing_tickers,
    )


_api_services = ApiServiceFactory(globals(), logger=LOGGER)
_legacy_api = LegacyApiFacade(
    api_services=_api_services,
    candidate_revalidation_module=candidate_revalidation,
    logger=LOGGER,
)

_SERVICE_FACTORY_DEPENDENCIES = (
    asyncio,
    get_settings,
    today_taipei,
    session_scope,
    CompanyFilingFetcher,
    filing_quality_score,
    filing_source_tier,
    MarketDataClient,
    NewsFetcher,
    NewsSourceStore,
    VectorStore,
    candidate_audit_summary,
    render_candidate_audit_markdown,
    audit_company_data,
    audit_report_company_data,
    CompanyDataAuditApiService,
    CompanyFilingApiService,
    DataOperationsApiService,
    CandidateRevalidationService,
    DiscoveryApiService,
    DiscoveredMarketDataService,
    DiscoveredTopicPipelineService,
    DiscoveredReportBuilderService,
    DiscoveryWorkflowService,
    EntityMapper,
    FollowUpActionPlanner,
    TRACKING_FRESHNESS_THRESHOLDS,
    execute_follow_up_actions,
    render_follow_up_actions_markdown,
    split_fresh_tracking_actions,
    summarize_follow_up_execution,
    IngestionPipeline,
    AnalysisRunRepository,
    CompanyFilingRepository,
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ReportRepository,
    ValuationMetricRepository,
    ReportBuildService,
    append_candidate_audit_if_missing,
    candidate_audit_from_run_payload,
    follow_up_action_summary,
    follow_up_plan_next_actions,
    latest_follow_up_run_for_report,
    parse_run_payload,
    serialize_run,
    should_require_candidate_audit_follow_up,
    summarize_candidate_support_payload,
    ReportFollowUpContextService,
    AutoFollowUpStartService,
    ReportFollowUpPlanService,
    ReportFollowUpRunService,
    SyncReportGenerationApiService,
    ReportGenerator,
    report_execution_summary,
    attach_quality_gate_to_report,
    build_quality_gate_for_request,
    build_report_quality_gate,
    should_recover_market_data_quality,
    parse_quality_gate_from_markdown,
    summarize_document_source_quality,
    summarize_llm_status,
    ReportQueryService,
    RunTaskApiService,
    RunStateService,
    LLMApiService,
    LLMClient,
    PipelineApiService,
    ScheduleConfigStore,
    filter_formal_evidence_documents,
    remove_low_quality_investor_forum_lines,
    SourceRelevanceAnalyzer,
    StandardReportPipelineService,
    SupplyChainGraphApiService,
    Neo4jGraphImportService,
    SupplyChainWhitelist,
    DISCOVERED_PIPELINE_STEPS,
    STANDARD_PIPELINE_STEPS,
    WorkflowCheckpointRecorder,
    WorkflowOrchestrationError,
    WorkflowOrchestrationRunner,
    celery_app,
    generate_report_task,
)


def safe_mark_run_failed(run_id: int, error: str) -> None:
    return _legacy_api.safe_mark_run_failed(run_id, error)


def safe_update_run_success(run_id: int, payload: dict, report_id: int) -> bool:
    return _legacy_api.safe_update_run_success(run_id, payload, report_id)


def load_report_follow_up_context(report_id: int) -> dict:
    return _legacy_api.load_report_follow_up_context(report_id)


def revalidate_candidate_whitelist(run_payload: dict, fallback_candidates: list[dict], limit: int = 500) -> dict:
    return _legacy_api.revalidate_candidate_whitelist(run_payload, fallback_candidates, limit)


def preserve_previous_supported_candidates(current_candidates: list[dict], previous_candidates: list[dict]) -> list[dict]:
    return _legacy_api.preserve_previous_supported_candidates(current_candidates, previous_candidates)


def mark_unavailable_candidates_after_revalidation(candidates: list[dict], document_count: int) -> list[dict]:
    return _legacy_api.mark_unavailable_candidates_after_revalidation(candidates, document_count)


def candidate_revalidation_queries(plan: TopicDiscoveryPlan, topic: str = "", limit: int = 80) -> list[str]:
    return _legacy_api.candidate_revalidation_queries(plan, topic, limit)


def collect_revalidation_documents(repository: NewsRepository, queries: list[str], limit: int) -> list:
    return _legacy_api.collect_revalidation_documents(repository, queries, limit)


def dedupe_documents(documents: list) -> list:
    return _legacy_api.dedupe_documents(documents)


def persist_candidate_entity_matches(
    plan: TopicDiscoveryPlan,
    candidates: list,
    documents: list,
) -> dict:
    return _legacy_api.persist_candidate_entity_matches(plan, candidates, documents)


def dedupe_strings(values: list[str], limit: int) -> list[str]:
    return _legacy_api.dedupe_strings(values, limit)


async def prepare_follow_up_report_context(
    context: dict,
    request: ReportRequest,
    actions: list,
) -> dict:
    return await _legacy_api.prepare_follow_up_report_context(context, request, actions)


async def refresh_market_data_for_report(request: ReportRequest) -> dict:
    return await _legacy_api.refresh_market_data_for_report(request)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="台股 AI 產業鏈 RAG 分析系統",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(
    create_system_router(
        db_status_func=db_status,
        service_status_func=service_status,
        upgrade_audit_func=audit_upgrade_capabilities,
    )
)
app.include_router(create_supply_chain_router(_api_services))
app.include_router(create_company_filing_router(_api_services))
app.include_router(
    create_pipeline_router(
        _api_services,
        report_execution_error_cls=ReportExecutionError,
        workflow_orchestration_error_cls=WorkflowOrchestrationError,
    )
)
app.include_router(
    create_operations_router(
        _api_services,
        async_report_validation_error_cls=AsyncReportValidationError,
        run_task_not_found_cls=RunTaskNotFound,
    )
)
app.include_router(create_ai_router(_api_services))


async def ingest_dynamic_news_urls(
    urls: list[str],
    limit_per_query: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    return await _legacy_api.ingest_dynamic_news_urls(urls, limit_per_query, start_date, end_date)


async def run_topic_discovery_ingestion(
    payload: TopicDiscoveryRequest,
    service: TopicDiscoveryService,
    plan: TopicDiscoveryPlan,
    limit_per_query: int,
    evidence_limit: int,
    max_queries: int,
    document_limit: int,
) -> dict:
    return await _legacy_api.run_topic_discovery_ingestion(
        payload,
        service,
        plan,
        limit_per_query,
        evidence_limit,
        max_queries,
        document_limit,
    )


async def discover_topic_with_timeout(service: TopicDiscoveryService, topic: str, timeout: int = 75) -> dict:
    return await _legacy_api.discover_topic_with_timeout(service, topic, timeout)


def get_report_follow_up_plan(report_id: int) -> dict:
    return _legacy_api.get_report_follow_up_plan(report_id)


async def maybe_auto_start_required_follow_up(report_id: int, run_in_background: bool = True) -> dict:
    return await _legacy_api.maybe_auto_start_required_follow_up(report_id, run_in_background)


async def run_required_follow_up_background(report_id: int, payload: FollowUpRunRequest) -> None:
    await _legacy_api.run_required_follow_up_background(report_id, payload)


async def run_report_follow_up(report_id: int, payload: Optional[FollowUpRunRequest] = None) -> dict:
    return await _legacy_api.run_report_follow_up(report_id, payload)


app.include_router(
    create_report_router(
        _api_services,
        report_execution_error_cls=ReportExecutionError,
        workflow_orchestration_error_cls=WorkflowOrchestrationError,
        report_query_not_found_cls=ReportQueryNotFound,
        company_data_audit_not_found_cls=CompanyDataAuditApiNotFound,
        get_follow_up_plan_func=lambda report_id: get_report_follow_up_plan(report_id),
        auto_start_follow_up_func=lambda report_id: maybe_auto_start_required_follow_up(report_id),
        run_follow_up_func=lambda report_id, payload=None: run_report_follow_up(report_id, payload),
    )
)
