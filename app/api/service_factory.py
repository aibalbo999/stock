from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any


class ApiServiceFactory:
    """Build API use-case services from the current application dependency namespace."""

    def __init__(self, dependencies: MutableMapping[str, Any], logger: logging.Logger | None = None) -> None:
        self.dependencies = dependencies
        self.logger = logger or logging.getLogger(__name__)

    def candidate_revalidation(self):
        d = self.dependencies
        return d["CandidateRevalidationService"](
            session_scope_factory=d["session_scope"],
            news_repository_cls=d["NewsRepository"],
            company_filing_repository_cls=d["CompanyFilingRepository"],
            topic_discovery_service_cls=d["TopicDiscoveryService"],
            whitelist_cls=d["SupplyChainWhitelist"],
        )

    def discovery_workflow(self):
        d = self.dependencies
        return d["DiscoveryWorkflowService"](
            session_scope_factory=d["session_scope"],
            ingestion_pipeline_cls=d["IngestionPipeline"],
            news_repository_cls=d["NewsRepository"],
            news_fetcher_cls=d["NewsFetcher"],
            entity_mapper_cls=d["EntityMapper"],
            vector_store_cls=d["VectorStore"],
            source_relevance_analyzer_cls=d["SourceRelevanceAnalyzer"],
            candidate_revalidation_service=self.candidate_revalidation(),
        )

    def discovered_market_data(self):
        d = self.dependencies
        return d["DiscoveredMarketDataService"](
            session_scope_factory=d["session_scope"],
            market_client_cls=d["MarketDataClient"],
            market_repository_cls=d["MarketRepository"],
            monthly_revenue_repository_cls=d["MonthlyRevenueRepository"],
            financial_metric_repository_cls=d["FinancialMetricRepository"],
            valuation_metric_repository_cls=d["ValuationMetricRepository"],
        )

    def discovered_report_builder(self):
        d = self.dependencies
        return d["DiscoveredReportBuilderService"](
            session_scope_factory=d["session_scope"],
            report_repository_cls=d["ReportRepository"],
            report_generator_cls=d["ReportGenerator"],
            report_request_cls=d["ReportRequest"],
            report_execution_summary_func=d["report_execution_summary"],
            build_report_quality_gate_func=d["build_report_quality_gate"],
            attach_quality_gate_to_report_func=d["attach_quality_gate_to_report"],
            summarize_document_source_quality_func=d["summarize_document_source_quality"],
            filter_formal_evidence_documents_func=d["filter_formal_evidence_documents"],
            summarize_llm_status_func=d["summarize_llm_status"],
            count_sufficient_company_filings_func=d["count_sufficient_company_filings"],
        )

    def report_build(self):
        d = self.dependencies
        return d["ReportBuildService"](
            report_generator_cls=d["ReportGenerator"],
            build_quality_gate_for_request_func=d["build_quality_gate_for_request"],
            attach_quality_gate_to_report_func=d["attach_quality_gate_to_report"],
            report_execution_summary_func=d["report_execution_summary"],
        )

    def sync_report_generation_api(self):
        d = self.dependencies
        settings_provider = d.get("get_settings")
        settings = settings_provider() if callable(settings_provider) else None
        sync_pre_refresh_enabled = (
            bool(getattr(settings, "sync_report_pre_refresh_enabled", False))
            if settings is not None
            else False
        )
        quality_recovery_enabled = (
            bool(getattr(settings, "report_quality_auto_recovery_enabled", True))
            if settings is not None
            else True
        )
        return d["SyncReportGenerationApiService"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            report_repository_cls=d["ReportRepository"],
            report_build_service_factory=self.report_build,
            count_sufficient_company_filings_func=d["count_sufficient_company_filings"],
            ingestion_pipeline_cls=d["IngestionPipeline"] if sync_pre_refresh_enabled else None,
            quality_recovery_pipeline_cls=d["IngestionPipeline"] if quality_recovery_enabled else None,
            market_quality_recovery_required_func=(
                d["should_recover_market_data_quality"]
                if quality_recovery_enabled
                else (lambda quality_gate: False)
            ),
        )

    def workflow_checkpoint_recorder(self):
        d = self.dependencies
        return d["WorkflowCheckpointRecorder"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
        )

    def workflow_orchestration_runner(self):
        d = self.dependencies
        return d["WorkflowOrchestrationRunner"](settings_provider=d["get_settings"])

    def run_state(self):
        d = self.dependencies
        return d["RunStateService"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
        )

    def report_follow_up_run(self):
        d = self.dependencies
        return d["ReportFollowUpRunService"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            report_repository_cls=d["ReportRepository"],
            follow_up_action_planner_cls=d["FollowUpActionPlanner"],
            load_report_follow_up_context_func=d["load_report_follow_up_context"],
            prepare_follow_up_report_context_func=d["prepare_follow_up_report_context"],
            execute_follow_up_actions_func=d["execute_follow_up_actions"],
            summarize_follow_up_execution_func=d["summarize_follow_up_execution"],
            split_fresh_tracking_actions_func=d["split_fresh_tracking_actions"],
            render_follow_up_actions_markdown_func=d["render_follow_up_actions_markdown"],
            report_build_service_factory=self.report_build,
            count_sufficient_company_filings_func=d["count_sufficient_company_filings"],
            safe_mark_run_failed_func=d["safe_mark_run_failed"],
            tracking_freshness_thresholds=d["TRACKING_FRESHNESS_THRESHOLDS"],
        )

    def report_follow_up_plan(self):
        d = self.dependencies
        return d["ReportFollowUpPlanService"](
            load_report_follow_up_context_func=d["load_report_follow_up_context"],
            follow_up_action_planner_cls=d["FollowUpActionPlanner"],
            should_require_candidate_audit_follow_up_func=d["should_require_candidate_audit_follow_up"],
            split_fresh_tracking_actions_func=d["split_fresh_tracking_actions"],
            follow_up_action_summary_func=d["follow_up_action_summary"],
            follow_up_plan_next_actions_func=d["follow_up_plan_next_actions"],
            render_follow_up_actions_markdown_func=d["render_follow_up_actions_markdown"],
            tracking_freshness_thresholds=d["TRACKING_FRESHNESS_THRESHOLDS"],
        )

    def auto_follow_up_start(self):
        d = self.dependencies
        return d["AutoFollowUpStartService"](
            settings_provider=d["get_settings"],
            plan_provider=d["get_report_follow_up_plan"],
            follow_up_run_request_cls=d["FollowUpRunRequest"],
            run_follow_up_func=d["run_report_follow_up"],
            background_runner_func=d["run_required_follow_up_background"],
            create_task_func=d["asyncio"].create_task,
        )

    def report_follow_up_context(self):
        d = self.dependencies
        return d["ReportFollowUpContextService"](
            session_scope_factory=d["session_scope"],
            report_repository_cls=d["ReportRepository"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            audit_company_data_func=d["audit_company_data"],
            parse_quality_gate_func=d["parse_quality_gate_from_markdown"],
            candidate_revalidation_service=self.candidate_revalidation(),
            supply_chain_whitelist_cls=d["SupplyChainWhitelist"],
            ingestion_pipeline_cls=d["IngestionPipeline"],
            today_func=d["today_taipei"],
            revalidate_candidate_whitelist_func=d["revalidate_candidate_whitelist"],
            refresh_market_data_func=d["refresh_market_data_for_report"],
        )

    def company_filing_api(self):
        d = self.dependencies
        return d["CompanyFilingApiService"](
            session_scope_factory=d["session_scope"],
            company_filing_fetcher_cls=d["CompanyFilingFetcher"],
            company_filing_repository_cls=d["CompanyFilingRepository"],
            vector_store_cls=d["VectorStore"],
            entity_mapper_cls=d["EntityMapper"],
            ingestion_pipeline_cls=d["IngestionPipeline"],
            filing_source_tier_func=d["filing_source_tier"],
            filing_quality_score_func=d["filing_quality_score"],
        )

    def report_query(self):
        d = self.dependencies
        return d["ReportQueryService"](
            session_scope_factory=d["session_scope"],
            report_repository_cls=d["ReportRepository"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            parse_run_payload_func=d["parse_run_payload"],
            candidate_audit_from_run_payload_func=d["candidate_audit_from_run_payload"],
            latest_follow_up_run_for_report_func=d["latest_follow_up_run_for_report"],
            remove_low_quality_lines_func=d["remove_low_quality_investor_forum_lines"],
            append_candidate_audit_func=d["append_candidate_audit_if_missing"],
            candidate_audit_summary_func=d["candidate_audit_summary"],
            render_candidate_audit_markdown_func=d["render_candidate_audit_markdown"],
        )

    def data_operations_api(self):
        d = self.dependencies
        return d["DataOperationsApiService"](
            session_scope_factory=d["session_scope"],
            news_repository_cls=d["NewsRepository"],
            market_repository_cls=d["MarketRepository"],
            valuation_metric_repository_cls=d["ValuationMetricRepository"],
            company_filing_repository_cls=d["CompanyFilingRepository"],
            financial_metric_repository_cls=d["FinancialMetricRepository"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            report_repository_cls=d["ReportRepository"],
            ingestion_pipeline_cls=d["IngestionPipeline"],
            news_fetcher_cls=d["NewsFetcher"],
            vector_store_cls=d["VectorStore"],
            news_source_store_cls=d["NewsSourceStore"],
            entity_mapper_cls=d["EntityMapper"],
            schedule_config_store_cls=d["ScheduleConfigStore"],
            today_func=d["today_taipei"],
        )

    def supply_chain_graph_api(self):
        d = self.dependencies
        return d["SupplyChainGraphApiService"](
            whitelist_cls=d["SupplyChainWhitelist"],
            neo4j_import_service_factory=lambda: d["Neo4jGraphImportService"](
                settings_provider=d["get_settings"],
            ),
        )

    def discovery_api(self):
        d = self.dependencies
        return d["DiscoveryApiService"](
            session_scope_factory=d["session_scope"],
            topic_discovery_service_cls=d["TopicDiscoveryService"],
            topic_discovery_plan_cls=d["TopicDiscoveryPlan"],
            news_repository_cls=d["NewsRepository"],
            ingestion_pipeline_cls=d["IngestionPipeline"],
            today_func=d["today_taipei"],
            discover_topic_with_timeout_func=d["discover_topic_with_timeout"],
            discovery_fetch_settings_func=d["discovery_fetch_settings"],
            discovery_document_limit_func=d["discovery_document_limit"],
            run_topic_discovery_ingestion_func=d["run_topic_discovery_ingestion"],
        )

    def llm_api(self):
        d = self.dependencies
        return d["LLMApiService"](
            llm_client_cls=d["LLMClient"],
            session_scope_factory=d["session_scope"],
            llm_usage_repository_cls=d["LLMUsageRepository"],
        )

    def company_data_audit_api(self):
        d = self.dependencies
        return d["CompanyDataAuditApiService"](
            session_scope_factory=d["session_scope"],
            audit_report_company_data_func=d["audit_report_company_data"],
        )

    def run_task_api(self):
        d = self.dependencies
        return d["RunTaskApiService"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            entity_mapper_cls=d["EntityMapper"],
            report_task=d["generate_report_task"],
            discovered_report_task=d["discovered_report_task"],
            data_operation_task=d["data_operation_task"],
            report_follow_up_task=d["report_follow_up_task"],
            celery_app=d["celery_app"],
            serialize_run_func=d["serialize_run"],
        )

    def pipeline_api(self):
        d = self.dependencies
        return d["PipelineApiService"](
            workflow_runner_factory=self.workflow_orchestration_runner,
            standard_pipeline_factory=self.standard_report_pipeline,
            discovered_pipeline_factory=self.discovered_topic_pipeline,
            run_state_factory=self.run_state,
            topic_discovery_request_cls=d["TopicDiscoveryRequest"],
        )

    def standard_report_pipeline(self):
        d = self.dependencies
        settings_provider = d.get("get_settings")
        settings = settings_provider() if callable(settings_provider) else None
        quality_recovery_enabled = (
            bool(getattr(settings, "report_quality_auto_recovery_enabled", True))
            if settings is not None
            else True
        )
        return d["StandardReportPipelineService"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            report_repository_cls=d["ReportRepository"],
            ingestion_pipeline_cls=d["IngestionPipeline"],
            report_build_service_factory=self.report_build,
            workflow_recorder_factory=self.workflow_checkpoint_recorder,
            auto_follow_up_func=lambda report_id: d["maybe_auto_start_required_follow_up"](
                report_id,
                run_in_background=False,
            ),
            safe_update_run_success_func=d["safe_update_run_success"],
            safe_mark_run_failed_func=d["safe_mark_run_failed"],
            workflow_steps=d["STANDARD_PIPELINE_STEPS"],
            market_quality_recovery_required_func=(
                d["should_recover_market_data_quality"]
                if quality_recovery_enabled
                else (lambda quality_gate: False)
            ),
        )

    def discovered_topic_pipeline(self):
        d = self.dependencies
        return d["DiscoveredTopicPipelineService"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            report_repository_cls=d["ReportRepository"],
            company_filing_repository_cls=d["CompanyFilingRepository"],
            topic_discovery_service_cls=d["TopicDiscoveryService"],
            topic_discovery_plan_cls=d["TopicDiscoveryPlan"],
            supply_chain_whitelist_cls=d["SupplyChainWhitelist"],
            workflow_recorder_factory=self.workflow_checkpoint_recorder,
            discovered_market_data_service_factory=self.discovered_market_data,
            discovered_report_builder_service_factory=self.discovered_report_builder,
            discover_topic_with_timeout_func=d["discover_topic_with_timeout"],
            discovery_fetch_settings_func=d["discovery_fetch_settings"],
            discovery_document_limit_func=d["discovery_document_limit"],
            run_topic_discovery_ingestion_func=d["run_topic_discovery_ingestion"],
            should_revalidate_candidate_filings_func=d["should_revalidate_candidate_filings"],
            candidate_filing_revalidation_tickers_func=d["candidate_filing_revalidation_tickers"],
            company_filing_timeout_result_func=d["company_filing_timeout_result"],
            dedupe_documents_func=d["dedupe_documents"],
            apply_company_filing_gate_func=d["apply_company_filing_gate_to_candidate_payload"],
            summarize_candidate_support_payload_func=d["summarize_candidate_support_payload"],
            summarize_candidate_support_func=d["summarize_candidate_support"],
            safe_update_run_success_func=d["safe_update_run_success"],
            safe_mark_run_failed_func=d["safe_mark_run_failed"],
            auto_follow_up_func=lambda report_id: d["maybe_auto_start_required_follow_up"](
                report_id,
                run_in_background=False,
            ),
            workflow_steps=d["DISCOVERED_PIPELINE_STEPS"],
        )
