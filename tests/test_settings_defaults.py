from app.core.config import Settings
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD


def test_settings_default_api_base_url() -> None:
    assert Settings(_env_file=None).api_base_url == "http://127.0.0.1:8000"


def test_database_init_mode_default_uses_deployment_migrations() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_init_mode == "alembic"
    assert settings.database_allow_create_all_non_sqlite is False


def test_candidate_confidence_threshold_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.candidate_confidence_high_threshold == HIGH_CONFIDENCE_THRESHOLD
    assert settings.candidate_confidence_medium_threshold == MEDIUM_CONFIDENCE_THRESHOLD


def test_market_data_cache_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.market_data_cache_enabled is True
    assert settings.market_price_provider_order == "finmind,fugle"
    assert settings.finmind_public_fallback_enabled is True
    assert settings.price_history_cache_ttl_seconds == 24 * 60 * 60
    assert settings.monthly_revenue_cache_ttl_seconds == 7 * 24 * 60 * 60
    assert settings.financial_metrics_cache_ttl_seconds == 31 * 24 * 60 * 60
    assert settings.valuation_metrics_cache_ttl_seconds == 24 * 60 * 60
    assert settings.finmind_max_retries == 2
    assert settings.finmind_base_retry_delay_seconds == 0.5
    assert settings.finmind_max_retry_delay_seconds == 5.0
    assert settings.finmind_timeout_seconds == 20.0
    assert settings.finmind_connect_timeout_seconds == 8.0
    assert settings.finmind_concurrency == 5
    assert settings.finmind_circuit_breaker_enabled is True
    assert settings.finmind_circuit_breaker_failure_threshold == 5
    assert settings.finmind_circuit_breaker_recovery_seconds == 60.0
    assert settings.fugle_max_retries == 2
    assert settings.fugle_base_retry_delay_seconds == 0.5
    assert settings.fugle_max_retry_delay_seconds == 5.0
    assert settings.fugle_timeout_seconds == 20.0
    assert settings.fugle_connect_timeout_seconds == 8.0
    assert settings.fugle_circuit_breaker_enabled is True
    assert settings.fugle_circuit_breaker_failure_threshold == 5
    assert settings.fugle_circuit_breaker_recovery_seconds == 60.0
    assert settings.market_official_openapi_fallback_enabled is True
    assert settings.market_official_openapi_timeout_seconds == 15.0


def test_company_filing_fetch_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.company_filing_user_agents == ""
    assert settings.company_filing_proxy_urls == ""
    assert settings.company_filing_http_retries == 1
    assert settings.company_filing_base_retry_delay_seconds == 0.5
    assert settings.company_filing_max_retry_delay_seconds == 5.0
    assert settings.company_filing_pdf_parser == "auto"
    assert settings.company_filing_pdf_extract_tables is True
    assert settings.company_filing_html_extract_tables is True
    assert settings.company_filing_cache_enabled is True
    assert settings.company_filing_cache_ttl_seconds == 7 * 24 * 60 * 60
    assert settings.company_filing_browser_render_enabled is False
    assert settings.company_filing_browser_render_provider == "browserless"
    assert settings.company_filing_browser_render_url == ""
    assert settings.company_filing_browser_render_token == ""
    assert settings.company_filing_browser_render_timeout_seconds == 30.0
    assert settings.company_filing_browser_render_concurrency == 4
    assert settings.company_filing_playwright_render_enabled is True
    assert settings.company_filing_playwright_browser == "chromium"
    assert settings.company_filing_playwright_wait_until == "networkidle"
    assert settings.company_filing_playwright_timeout_seconds == 30.0
    assert settings.company_filing_structured_api_provider == ""
    assert settings.company_filing_structured_api_url == ""
    assert settings.company_filing_structured_api_token == ""
    assert settings.company_filing_structured_api_timeout_seconds == 20.0


def test_workflow_orchestration_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.workflow_engine == "local"
    assert settings.workflow_local_fallback_enabled is True
    assert settings.prefect_api_url == ""
    assert settings.temporal_address == "localhost:7233"
    assert settings.temporal_namespace == "default"
    assert settings.temporal_task_queue == "stock-analysis"
    assert settings.temporal_workflow_name == "StockAnalysisPipeline"
    assert settings.temporal_ui_url == ""
    assert settings.temporal_timeout_seconds == 15.0
    assert settings.airflow_api_url == ""
    assert settings.airflow_dag_id == "stock_analysis_pipeline"
    assert settings.airflow_api_token is None
    assert settings.airflow_username == ""
    assert settings.airflow_password is None
    assert settings.airflow_timeout_seconds == 15.0
