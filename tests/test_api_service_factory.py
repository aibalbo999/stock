from __future__ import annotations

from types import SimpleNamespace

from app.api.service_factory import ApiServiceFactory
from app.api.service_factory_data import DataServiceFactoryMixin
from app.api.service_factory_report import ReportServiceFactoryMixin
from app.api.service_factory_workflow import WorkflowServiceFactoryMixin
from app.services.report_generation_api import SyncReportGenerationApiService


class DummyIngestionPipeline:
    pass


class DummyAnalysisRunRepository:
    pass


class DummyReportRepository:
    pass


def test_api_service_factory_uses_domain_mixins() -> None:
    assert issubclass(ApiServiceFactory, DataServiceFactoryMixin)
    assert issubclass(ApiServiceFactory, ReportServiceFactoryMixin)
    assert issubclass(ApiServiceFactory, WorkflowServiceFactoryMixin)
    assert ApiServiceFactory.data_operations_api is DataServiceFactoryMixin.data_operations_api
    assert ApiServiceFactory.discovery_api is DataServiceFactoryMixin.discovery_api
    assert ApiServiceFactory.report_query is ReportServiceFactoryMixin.report_query
    assert ApiServiceFactory.sync_report_generation_api is ReportServiceFactoryMixin.sync_report_generation_api
    assert ApiServiceFactory.run_task_api is WorkflowServiceFactoryMixin.run_task_api
    assert ApiServiceFactory.pipeline_api is WorkflowServiceFactoryMixin.pipeline_api


def test_sync_report_generation_factory_disables_network_recovery_by_default() -> None:
    service, _should_recover = _sync_report_generation_service(
        SimpleNamespace(
            sync_report_pre_refresh_enabled=False,
            sync_report_quality_recovery_enabled=False,
            report_quality_auto_recovery_enabled=True,
        )
    )

    assert service.ingestion_pipeline_cls is None
    assert service.quality_recovery_pipeline_cls is None
    assert service.market_quality_recovery_required_func({"status": "caution"}) is False


def test_sync_report_generation_factory_can_opt_into_sync_network_recovery() -> None:
    service, should_recover = _sync_report_generation_service(
        SimpleNamespace(
            sync_report_pre_refresh_enabled=True,
            sync_report_quality_recovery_enabled=True,
            report_quality_auto_recovery_enabled=True,
        )
    )

    assert service.ingestion_pipeline_cls is DummyIngestionPipeline
    assert service.quality_recovery_pipeline_cls is DummyIngestionPipeline
    assert service.market_quality_recovery_required_func is should_recover
    assert service.market_quality_recovery_required_func({"status": "caution"}) is True


def test_sync_report_generation_factory_honors_global_recovery_disable() -> None:
    service, _should_recover = _sync_report_generation_service(
        SimpleNamespace(
            sync_report_pre_refresh_enabled=False,
            sync_report_quality_recovery_enabled=True,
            report_quality_auto_recovery_enabled=False,
        )
    )

    assert service.quality_recovery_pipeline_cls is None
    assert service.market_quality_recovery_required_func({"status": "caution"}) is False


def _sync_report_generation_service(settings):
    def should_recover_market_data_quality(_quality_gate) -> bool:
        return True

    dependencies = {
        "get_settings": lambda: settings,
        "SyncReportGenerationApiService": SyncReportGenerationApiService,
        "session_scope": lambda: None,
        "AnalysisRunRepository": DummyAnalysisRunRepository,
        "ReportRepository": DummyReportRepository,
        "count_sufficient_company_filings": lambda tickers: 0,
        "IngestionPipeline": DummyIngestionPipeline,
        "should_recover_market_data_quality": should_recover_market_data_quality,
    }

    service = ApiServiceFactory(dependencies).sync_report_generation_api()
    return service, should_recover_market_data_quality
