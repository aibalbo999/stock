from __future__ import annotations


class DataServiceFactoryMixin:
    """Data, discovery, and filing service wiring for ApiServiceFactory."""

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

    def discovered_market_data(self, cancellation_checker=None):
        d = self.dependencies
        return d["DiscoveredMarketDataService"](
            session_scope_factory=d["session_scope"],
            market_client_cls=d["MarketDataClient"],
            market_repository_cls=d["MarketRepository"],
            monthly_revenue_repository_cls=d["MonthlyRevenueRepository"],
            financial_metric_repository_cls=d["FinancialMetricRepository"],
            valuation_metric_repository_cls=d["ValuationMetricRepository"],
            cancellation_checker=cancellation_checker,
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
