from pathlib import Path

from app.core.config import Settings
from app.data_sources.company_filings import COMPANY_FILING_RETRYABLE_HTTP_STATUSES
from app.data_sources.market import FUGLE_RETRYABLE_HTTP_STATUSES, FINMIND_RETRYABLE_HTTP_STATUSES
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD
from app.services.service_status import (
    _redact_url,
    service_status,
)
from app.services.status_company_filings import (
    _company_filing_pdf_parser_status,
    _company_filing_user_agent_status,
)
from app.services.status_market_data import _market_data_provider_readiness


def test_redact_url_with_password() -> None:
    assert _redact_url("redis://user:secret@localhost:6379/0") == "redis://user:***@localhost:6379/0"


def test_service_status_shape() -> None:
    status = service_status()
    service_status_source = Path("app/services/service_status.py").read_text()
    status_market_data_source = Path("app/services/status_market_data.py").read_text()
    status_company_filings_source = Path("app/services/status_company_filings.py").read_text()

    assert "database" in status
    assert "redis" in status
    assert "gemini" in status
    assert "finmind" in status
    assert "fugle" in status
    assert "market_data_cache" in status
    assert "company_filings" in status
    assert "vector_store" in status
    assert "supply_chain_graph" in status
    assert "workflow_orchestration" in status
    assert "python_runtime" in status
    assert "task_queue" in status
    assert status["market_data_cache"]["enabled"] is True
    assert status["market_data_cache"]["available"] == bool(status["redis"]["ok"])
    assert status["market_data_cache"]["stale_rescue_enabled"] is True
    assert status["market_data_cache"]["stale_source_marker"] == "cached-stale"
    assert status["market_data_cache"]["latest_only_source_marker"] == "latest-only"
    assert status["market_data_cache"]["price_provider_order"] == ["finmind", "fugle"]
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["live_providers"] == [
        "finmind",
        "fugle",
        "twse_tpex_openapi_latest",
    ]
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["fallback_enabled"] is True
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["fugle_fallback_endpoints"] == [
        "historical/candles",
        "historical/stats",
    ]
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["official_openapi_latest_snapshot_fallback"] is True
    assert status["market_data_cache"]["provider_matrix"]["monthly_revenue"]["live_providers"] == [
        "finmind",
        "twse_tpex_openapi_latest",
    ]
    assert status["market_data_cache"]["provider_matrix"]["monthly_revenue"]["fallback_enabled"] is True
    assert status["market_data_cache"]["provider_matrix"]["financial_metrics"]["fallback_enabled"] is True
    assert (
        status["market_data_cache"]["provider_matrix"]["financial_metrics"]["official_openapi_scope"]
        == "latest_quarter_income_balance_only"
    )
    assert (
        status["market_data_cache"]["provider_matrix"]["valuation"]["redis_cache_ttl_seconds"]
        == Settings().valuation_metrics_cache_ttl_seconds
    )
    assert "TaiwanStockPER" in status["market_data_cache"]["datasets"]
    assert status["market_data_cache"]["price_history_ttl_seconds"] == Settings().price_history_cache_ttl_seconds
    assert status["market_data_cache"]["monthly_revenue_ttl_seconds"] == Settings().monthly_revenue_cache_ttl_seconds
    assert status["market_data_cache"]["financial_metrics_ttl_seconds"] == Settings().financial_metrics_cache_ttl_seconds
    assert status["market_data_cache"]["valuation_metrics_ttl_seconds"] == Settings().valuation_metrics_cache_ttl_seconds
    assert status["market_data_cache"]["official_openapi_fallback_enabled"] is True
    assert status["market_data_cache"]["official_openapi_timeout_seconds"] == 15.0
    assert status["finmind"]["collector_path"] == "app/services/status_market_data.py"
    assert status["fugle"]["collector_path"] == "app/services/status_market_data.py"
    assert status["market_data_cache"]["collector_path"] == "app/services/status_market_data.py"
    assert "from app.services.status_market_data import (" in service_status_source
    assert "def _market_data_provider_matrix(" not in service_status_source
    assert "def market_data_status(" in status_market_data_source
    assert status["company_filings"]["http_retries"] == Settings().company_filing_http_retries
    assert status["company_filings"]["collector_path"] == "app/services/status_company_filings.py"
    assert "from app.services.status_company_filings import (" in service_status_source
    assert "def _company_filing_pdf_parser_status(" not in service_status_source
    assert "def company_filing_status(" in status_company_filings_source
    assert status["company_filings"]["retryable_http_statuses"] == sorted(COMPANY_FILING_RETRYABLE_HTTP_STATUSES)
    assert (
        status["company_filings"]["base_retry_delay_seconds"]
        == Settings().company_filing_base_retry_delay_seconds
    )
    assert (
        status["company_filings"]["max_retry_delay_seconds"]
        == Settings().company_filing_max_retry_delay_seconds
    )
    assert status["company_filings"]["pdf_parser"] == Settings().company_filing_pdf_parser
    assert status["company_filings"]["pdf_extract_tables"] is True
    assert "pdfplumber_available" in status["company_filings"]["pdf_parser_dependencies"]
    assert "unstructured_pdf_available" in status["company_filings"]["pdf_parser_dependencies"]
    assert status["company_filings"]["pdf_parser_available"] is status["company_filings"][
        "pdf_parser_dependencies"
    ]["configured_parser_available"]
    assert status["company_filings"]["pdf_table_parser_available"] is status["company_filings"][
        "pdf_parser_dependencies"
    ]["table_parser_available"]
    assert status["company_filings"]["html_extract_tables"] is True
    assert status["company_filings"]["cache_enabled"] is True
    assert status["company_filings"]["cache_available"] == bool(status["redis"]["ok"])
    assert status["company_filings"]["cache_backend"] == "redis"
    assert status["company_filings"]["cache_key_namespace"] == "stock-ai:company-filing:url-document:v1"
    assert status["company_filings"]["cache_key_scope"] == [
        "url",
        "parser",
        "extract_tables",
        "html_extract_tables",
    ]
    assert status["company_filings"]["cache_ttl_seconds"] == Settings().company_filing_cache_ttl_seconds
    assert status["company_filings"]["browser_render_enabled"] is False
    assert status["company_filings"]["browser_render_provider"] == "browserless"
    assert "flaresolverr" in status["company_filings"]["browser_render_supported_providers"]
    assert status["company_filings"]["browser_render_configured"] is False
    assert status["company_filings"]["browser_render_endpoint_reachable"] is False
    assert "fallback_reason" in status["company_filings"]["browser_render_runtime"]
    assert status["company_filings"]["browser_render_runtime"]["smoke_cli"].endswith(
        "scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    )
    assert status["company_filings"]["browser_render_timeout_seconds"] == 30.0
    assert status["company_filings"]["structured_api_configured"] is False
    assert status["company_filings"]["structured_api_provider"] is None
    assert status["company_filings"]["structured_api_url_configured"] is False
    assert status["company_filings"]["structured_api_token_configured"] is False
    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_configured"] is bool(
        status["company_filings"]["playwright_render_browser_available"]
    )
    assert isinstance(status["company_filings"]["playwright_render_dependency_available"], bool)
    assert isinstance(status["company_filings"]["playwright_render_browser_available"], bool)
    assert "fallback_reason" in status["company_filings"]["playwright_render_runtime"]
    assert status["company_filings"]["playwright_render_runtime"]["smoke_cli"].endswith(
        "scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    )
    assert status["company_filings"]["playwright_render_browser"] == "chromium"
    assert status["company_filings"]["playwright_render_wait_until"] == "networkidle"
    assert status["company_filings"]["playwright_render_timeout_seconds"] == 30.0
    assert status["company_filings"]["custom_user_agent_count"] == 0
    assert status["company_filings"]["default_user_agent_count"] >= 1
    assert status["company_filings"]["effective_user_agent_count"] >= 1
    assert status["company_filings"]["user_agent_mode"] == "default_browser_like"
    assert status["company_filings"]["anti_crawl_identity_enabled"] is True
    assert status["company_filings"]["user_agent_retry_rotation_enabled"] is True
    assert status["company_filings"]["proxy_retry_rotation_enabled"] is False
    assert status["company_filings"]["identity_retry_rotation_enabled"] is True
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is bool(
        status["company_filings"]["browser_render_configured"]
        or status["company_filings"]["playwright_render_configured"]
        or status["company_filings"]["proxy_count"]
    )
    assert status["finmind"]["retryable_http_statuses"] == sorted(FINMIND_RETRYABLE_HTTP_STATUSES)
    assert status["finmind"]["public_fallback_enabled"] is True
    assert status["finmind"]["data_access_ready"] is True
    assert status["finmind"]["mode"] in {"authenticated", "public_limited"}
    assert status["finmind"]["max_retries"] == Settings().finmind_max_retries
    assert status["finmind"]["base_retry_delay_seconds"] == Settings().finmind_base_retry_delay_seconds
    assert status["finmind"]["max_retry_delay_seconds"] == Settings().finmind_max_retry_delay_seconds
    assert status["finmind"]["timeout_seconds"] == Settings().finmind_timeout_seconds
    assert status["finmind"]["connect_timeout_seconds"] == Settings().finmind_connect_timeout_seconds
    assert status["finmind"]["concurrency"] == Settings().finmind_concurrency
    assert status["finmind"]["circuit_breaker_enabled"] == Settings().finmind_circuit_breaker_enabled
    assert (
        status["finmind"]["circuit_breaker_failure_threshold"]
        == Settings().finmind_circuit_breaker_failure_threshold
    )
    assert (
        status["finmind"]["circuit_breaker_recovery_seconds"]
        == Settings().finmind_circuit_breaker_recovery_seconds
    )
    assert status["fugle"]["configured"] is False
    assert status["fugle"]["price_history_provider"] is True
    assert status["fugle"]["price_fallback_endpoints"] == ["historical/candles", "historical/stats"]
    assert status["fugle"]["provider_order"] == ["finmind", "fugle"]
    assert status["fugle"]["retryable_http_statuses"] == sorted(FUGLE_RETRYABLE_HTTP_STATUSES)
    assert status["fugle"]["max_retries"] == Settings().fugle_max_retries
    assert status["fugle"]["base_retry_delay_seconds"] == Settings().fugle_base_retry_delay_seconds
    assert status["fugle"]["max_retry_delay_seconds"] == Settings().fugle_max_retry_delay_seconds
    assert status["fugle"]["timeout_seconds"] == Settings().fugle_timeout_seconds
    assert status["fugle"]["connect_timeout_seconds"] == Settings().fugle_connect_timeout_seconds
    assert status["fugle"]["circuit_breaker_enabled"] == Settings().fugle_circuit_breaker_enabled
    assert (
        status["fugle"]["circuit_breaker_failure_threshold"]
        == Settings().fugle_circuit_breaker_failure_threshold
    )
    assert (
        status["fugle"]["circuit_breaker_recovery_seconds"]
        == Settings().fugle_circuit_breaker_recovery_seconds
    )
    assert status["candidate_confidence"]["high_threshold"] == HIGH_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["medium_threshold"] == MEDIUM_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["source_credibility_weights"]["official"] == 1.0
    assert status["candidate_confidence"]["source_credibility_weights"]["investment_blog"] < 0.75


def test_company_filing_user_agent_status_uses_default_browser_like_agents() -> None:
    status = _company_filing_user_agent_status("")

    assert status["custom_user_agent_count"] == 0
    assert status["default_user_agent_count"] >= 1
    assert status["effective_user_agent_count"] == status["default_user_agent_count"]
    assert status["user_agent_mode"] == "default_browser_like"
    assert status["anti_crawl_identity_enabled"] is True


def test_company_filing_pdf_parser_status_requires_table_capable_dependency() -> None:
    def fake_module_available(name: str) -> bool:
        return name == "pypdf"

    status = _company_filing_pdf_parser_status(
        "auto",
        extract_tables=True,
        module_available=fake_module_available,
    )

    assert status["configured_parser_available"] is True
    assert status["resolved_parser_candidates"] == ["pypdf"]
    assert status["table_parser_available"] is False
    assert status["table_extraction_runtime_available"] is False
    assert status["fallback_reason"] == "missing_table_pdf_parser_dependency:pdfplumber_or_unstructured"


def test_company_filing_pdf_parser_status_accepts_pdfplumber_for_tables() -> None:
    def fake_module_available(name: str) -> bool:
        return name == "pdfplumber"

    status = _company_filing_pdf_parser_status(
        "auto",
        extract_tables=True,
        module_available=fake_module_available,
    )

    assert status["configured_parser_available"] is True
    assert status["resolved_parser_candidates"] == ["pdfplumber"]
    assert status["table_parser_available"] is True
    assert status["table_extraction_runtime_available"] is True
    assert status["fallback_reason"] is None


def test_company_filing_user_agent_status_counts_custom_agents() -> None:
    status = _company_filing_user_agent_status("UA-A,UA-B")

    assert status["custom_user_agent_count"] == 2
    assert status["effective_user_agent_count"] == 2
    assert status["user_agent_mode"] == "custom"
    assert status["anti_crawl_identity_enabled"] is True


def test_market_data_provider_readiness_distinguishes_public_finmind_and_rescue_sources() -> None:
    degraded = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"]},
        {"configured": False, "public_fallback_enabled": False, "data_access_ready": False},
        {"configured": False},
    )

    assert degraded["ready"] is False
    assert degraded["finmind_authenticated"] is False
    assert degraded["finmind_public_fallback_enabled"] is False
    assert degraded["finmind_data_access_ready"] is False
    assert degraded["fugle_price_fallback_configured"] is False
    assert degraded["official_openapi_fallback_enabled"] is False
    assert degraded["official_openapi_fallback_scope"] == []
    assert "missing_finmind_access" in degraded["fallback_reason"]
    assert "missing_price_rescue_provider" in degraded["fallback_reason"]

    ready = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"]},
        {"configured": True, "public_fallback_enabled": False, "data_access_ready": True},
        {"configured": True},
    )

    assert ready["ready"] is True
    assert ready["fallback_reason"] is None

    official = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"], "official_openapi_fallback_enabled": True},
        {"configured": False, "public_fallback_enabled": True, "data_access_ready": True},
        {"configured": False},
    )

    assert official["ready"] is True
    assert official["finmind_access_mode"] == "public_limited"
    assert official["official_openapi_fallback_enabled"] is True
    assert "latest_quarter_income_balance" in official["official_openapi_fallback_scope"]
    assert "finmind_public_limited_mode_for_history_datasets" in official["warnings"]
    assert "missing_fugle_api_key_for_price_fallback" in official["warnings"]
