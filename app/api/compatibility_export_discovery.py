from __future__ import annotations

# ruff: noqa: F401

from app.api.schemas import TopicDiscoveryRequest
from app.services.discovered_candidate_filings import (
    candidate_filing_revalidation_tickers,
    company_filing_timeout_result,
    should_revalidate_candidate_filings,
)
from app.services.discovered_market_data import (
    DiscoveredMarketDataService,
    market_timeout_errors,
    merge_financial_metric_history,
    merge_latest_by_ticker,
)
from app.services.discovered_pipeline import DiscoveredTopicPipelineService
from app.services.discovered_report_builder import DiscoveredReportBuilderService
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
from app.services.entity_mapping import EntityMapper
from app.services.topic_discovery import TopicDiscoveryService
from app.services.topic_discovery_models import TopicDiscoveryPlan
from app.services.whitelist import SupplyChainWhitelist

DISCOVERY_LEGACY_HELPER_EXPORT_NAMES = (
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

DISCOVERY_EXPORT_NAMES = (
    "DiscoveryApiService",
    "DiscoveredMarketDataService",
    "DiscoveredTopicPipelineService",
    "DiscoveredReportBuilderService",
    "DiscoveryWorkflowService",
    "EntityMapper",
    "TopicDiscoveryPlan",
    "TopicDiscoveryRequest",
    "TopicDiscoveryService",
    "SupplyChainWhitelist",
    *DISCOVERY_LEGACY_HELPER_EXPORT_NAMES,
)


def compatibility_discovery_export_namespace() -> dict[str, object]:
    return {name: globals()[name] for name in DISCOVERY_EXPORT_NAMES}
