from __future__ import annotations


class WorkflowServiceFactoryMixin:
    """Workflow, task, and pipeline orchestration wiring for ApiServiceFactory."""

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
            settings_provider=d["get_settings"],
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
