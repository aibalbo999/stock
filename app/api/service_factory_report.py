from __future__ import annotations


class ReportServiceFactoryMixin:
    """Report-domain service wiring for ApiServiceFactory."""

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
        sync_quality_recovery_enabled = (
            quality_recovery_enabled
            and bool(getattr(settings, "sync_report_quality_recovery_enabled", False))
            if settings is not None
            else False
        )
        return d["SyncReportGenerationApiService"](
            session_scope_factory=d["session_scope"],
            analysis_run_repository_cls=d["AnalysisRunRepository"],
            report_repository_cls=d["ReportRepository"],
            report_build_service_factory=self.report_build,
            count_sufficient_company_filings_func=d["count_sufficient_company_filings"],
            ingestion_pipeline_cls=d["IngestionPipeline"] if sync_pre_refresh_enabled else None,
            quality_recovery_pipeline_cls=d["IngestionPipeline"] if sync_quality_recovery_enabled else None,
            market_quality_recovery_required_func=(
                d["should_recover_market_data_quality"]
                if sync_quality_recovery_enabled
                else (lambda quality_gate: False)
            ),
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

    def company_data_audit_api(self):
        d = self.dependencies
        return d["CompanyDataAuditApiService"](
            session_scope_factory=d["session_scope"],
            audit_report_company_data_func=d["audit_report_company_data"],
        )
