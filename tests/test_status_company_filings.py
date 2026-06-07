from pathlib import Path

from app.core.config import Settings
from app.data_sources.company_filings import COMPANY_FILING_RETRYABLE_HTTP_STATUSES
from app.services.status_company_filings import (
    _company_filing_pdf_parser_status,
    _company_filing_user_agent_status,
)


def test_company_filing_status_parser_cache_render_and_identity_evidence(
    service_status_snapshot,
) -> None:
    status = service_status_snapshot
    settings = Settings()
    service_status_source = Path("app/services/service_status.py").read_text()
    status_company_filings_source = Path("app/services/status_company_filings.py").read_text()

    assert status["company_filings"]["http_retries"] == settings.company_filing_http_retries
    assert status["company_filings"]["collector_path"] == "app/services/status_company_filings.py"
    assert "from app.services.status_company_filings import (" in service_status_source
    assert "def _company_filing_pdf_parser_status(" not in service_status_source
    assert "def company_filing_status(" in status_company_filings_source
    assert status["company_filings"]["retryable_http_statuses"] == sorted(
        COMPANY_FILING_RETRYABLE_HTTP_STATUSES
    )
    assert (
        status["company_filings"]["base_retry_delay_seconds"]
        == settings.company_filing_base_retry_delay_seconds
    )
    assert (
        status["company_filings"]["max_retry_delay_seconds"]
        == settings.company_filing_max_retry_delay_seconds
    )
    assert status["company_filings"]["pdf_parser"] == settings.company_filing_pdf_parser
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
    assert status["company_filings"]["cache_key_namespace"] == (
        "stock-ai:company-filing:url-document:v1"
    )
    assert status["company_filings"]["cache_key_scope"] == [
        "url",
        "parser",
        "extract_tables",
        "html_extract_tables",
    ]
    assert status["company_filings"]["cache_ttl_seconds"] == settings.company_filing_cache_ttl_seconds
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
    assert "structured_company_filing_sample.json" in status["company_filings"][
        "structured_api_runtime"
    ]["sample_contract_cli"]
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
