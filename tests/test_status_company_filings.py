from pathlib import Path

from app.core.config import Settings
from app.data_sources.company_filing_http import COMPANY_FILING_RETRYABLE_HTTP_STATUSES
from app.services.status_company_filings import (
    _company_filing_high_risk_source_policy,
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
    assert "pymupdf_available" in status["company_filings"]["pdf_parser_dependencies"]
    assert (
        status["company_filings"]["pdf_parser_available"]
        is status["company_filings"]["pdf_parser_dependencies"]["configured_parser_available"]
    )
    assert (
        status["company_filings"]["pdf_table_parser_available"]
        is status["company_filings"]["pdf_parser_dependencies"]["table_parser_available"]
    )
    assert status["company_filings"]["pdf_table_quality_provenance_enabled"] is True
    assert status["company_filings"]["pdf_table_quality_provenance_prefix"] == "[PDF 表格品質]"
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
    assert (
        status["company_filings"]["cache_ttl_seconds"] == settings.company_filing_cache_ttl_seconds
    )
    assert status["company_filings"]["browser_render_enabled"] is False
    assert status["company_filings"]["browser_render_provider"] == "browserless"
    assert "flaresolverr" in status["company_filings"]["browser_render_supported_providers"]
    assert status["company_filings"]["browser_render_provider_capability"]["tier"] == (
        "browser_render"
    )
    assert (
        status["company_filings"]["browser_render_provider_capability"]["captcha_unlocker"] is False
    )
    assert status["company_filings"]["browser_render_configured"] is False
    assert status["company_filings"]["browser_render_configuration_ready"] is False
    assert status["company_filings"]["browser_render_configuration_check"]["status"] == "disabled"
    assert status["company_filings"]["browser_render_configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    ]
    assert status["company_filings"]["browser_render_token_required"] is False
    assert status["company_filings"]["browser_render_token_configured"] is False
    assert status["company_filings"]["browser_render_endpoint_reachable"] is False
    assert "fallback_reason" in status["company_filings"]["browser_render_runtime"]
    assert "mops.twse.com.tw" in status["company_filings"]["high_risk_source_domains"]
    assert (
        status["company_filings"]["high_risk_source_policy"]["configured_provider"] == "browserless"
    )
    assert (
        "flaresolverr"
        in status["company_filings"]["high_risk_source_policy"]["recommended_unlocker_providers"]
    )
    assert (
        status["company_filings"]["high_risk_source_policy"]["configuration_check"]
        == status["company_filings"]["browser_render_configuration_check"]
    )
    assert status["company_filings"]["high_risk_captcha_unlocker_ready"] is False
    assert status["company_filings"]["browser_render_runtime"]["smoke_cli"].endswith(
        "scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    )
    assert status["company_filings"]["browser_render_provider_contract_ready"] is True
    assert status["company_filings"]["browser_render_provider_contract"]["provider_count"] == 5
    assert "flaresolverr" in {
        row["provider"]
        for row in status["company_filings"]["browser_render_provider_contract"]["providers"]
    }
    assert status["company_filings"]["browser_render_provider_contract_smoke_cli"].endswith(
        "scripts/company_filing_render_smoke.py --provider-contract --json"
    )
    assert status["company_filings"]["browser_render_timeout_seconds"] == 30.0
    assert status["company_filings"]["structured_api_configured"] is False
    assert status["company_filings"]["structured_api_configuration_ready"] is False
    assert status["company_filings"]["structured_api_provider"] is None
    assert status["company_filings"]["structured_api_url_configured"] is False
    assert status["company_filings"]["structured_api_token_configured"] is False
    assert status["company_filings"]["structured_api_configuration_check"]["status"] == (
        "missing_required_env"
    )
    assert status["company_filings"]["structured_api_configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
    ]
    assert status["company_filings"]["structured_api_runtime"]["provider_profile_key"] == "custom"
    assert (
        status["company_filings"]["structured_api_runtime"]["configuration_check"]
        == status["company_filings"]["structured_api_configuration_check"]
    )
    assert (
        status["company_filings"]["structured_api_runtime"]["request_contract"]["method"] == "GET"
    )
    assert (
        "tej" in status["company_filings"]["structured_api_runtime"]["supported_provider_profiles"]
    )
    assert (
        status["company_filings"]["structured_api_runtime"]["supported_provider_profiles"][
            "scrapingbee_dataset"
        ]["token_location"]
        == "query_param"
    )
    structured_decision_matrix = {
        row["provider"]: row
        for row in status["company_filings"]["structured_api_runtime"][
            "provider_decision_matrix"
        ]
    }
    assert structured_decision_matrix["tej"]["token_required"] is True
    assert structured_decision_matrix["custom"]["token_required"] is False
    assert "TEJ" in status["company_filings"]["structured_api_runtime"][
        "provider_selection_hint"
    ]
    assert (
        "structured_company_filing_sample.json"
        in status["company_filings"]["structured_api_runtime"]["sample_contract_cli"]
    )
    assert status["company_filings"]["official_material_information_openapi_ready"] is True
    assert status["company_filings"]["official_material_information_openapi_configured"] is True
    assert (
        status["company_filings"]["official_material_information_openapi_provider"]
        == "twse_tpex_official_openapi"
    )
    material_openapi_runtime = status["company_filings"][
        "official_material_information_openapi_runtime"
    ]
    assert material_openapi_runtime["requires_api_key"] is False
    assert material_openapi_runtime["source_urls"]["twse"].endswith("/opendata/t187ap04_L")
    assert material_openapi_runtime["source_urls"]["tpex"].endswith("/mopsfin_t187ap04_O")
    assert material_openapi_runtime["discovery_order"] == [
        "structured_api",
        "official_material_information_openapi",
        "google_news_rss",
    ]
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
    assert (
        status["fallback_reason"]
        == "missing_table_pdf_parser_dependency:pdfplumber_or_unstructured"
    )


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


def test_company_filing_pdf_parser_status_accepts_pymupdf_as_text_fallback() -> None:
    def fake_module_available(name: str) -> bool:
        return name == "fitz"

    no_table_status = _company_filing_pdf_parser_status(
        "auto",
        extract_tables=False,
        module_available=fake_module_available,
    )
    table_status = _company_filing_pdf_parser_status(
        "pymupdf",
        extract_tables=True,
        module_available=fake_module_available,
    )

    assert no_table_status["configured_parser_available"] is True
    assert no_table_status["resolved_parser_candidates"] == ["pymupdf"]
    assert no_table_status["pymupdf_available"] is True
    assert no_table_status["table_parser_available"] is False
    assert no_table_status["fallback_reason"] is None
    assert table_status["configured_parser_available"] is True
    assert table_status["resolved_parser_candidates"] == ["pymupdf"]
    assert table_status["table_extraction_runtime_available"] is False
    assert (
        table_status["fallback_reason"]
        == "missing_table_pdf_parser_dependency:pdfplumber_or_unstructured"
    )


def test_company_filing_user_agent_status_counts_custom_agents() -> None:
    status = _company_filing_user_agent_status("UA-A,UA-B")

    assert status["custom_user_agent_count"] == 2
    assert status["effective_user_agent_count"] == 2
    assert status["user_agent_mode"] == "custom"
    assert status["anti_crawl_identity_enabled"] is True


def test_company_filing_high_risk_source_policy_requires_unlocker_for_captcha() -> None:
    browserless_policy = _company_filing_high_risk_source_policy(
        browser_render_runtime={
            "provider": "browserless",
            "runtime_available": True,
            "provider_capability": {"tier": "browser_render", "captcha_unlocker": False},
        },
        playwright_configured=True,
        proxy_count=0,
    )
    unlocker_policy = _company_filing_high_risk_source_policy(
        browser_render_runtime={
            "provider": "flaresolverr",
            "runtime_available": True,
            "provider_capability": {"tier": "unlocker", "captcha_unlocker": True},
        },
        playwright_configured=False,
        proxy_count=0,
    )

    assert browserless_policy["browser_only_render_ready"] is True
    assert browserless_policy["captcha_challenge_ready"] is False
    assert (
        browserless_policy["fallback_reason"]
        == "browser_or_playwright_render_lacks_captcha_unlocker"
    )
    assert unlocker_policy["captcha_challenge_ready"] is True
    assert unlocker_policy["high_risk_mitigation_ready"] is True
    assert unlocker_policy["fallback_reason"] is None


def test_company_filing_high_risk_source_policy_surfaces_unlocker_configuration_gap() -> None:
    policy = _company_filing_high_risk_source_policy(
        browser_render_runtime={
            "provider": "scrapingbee",
            "runtime_available": False,
            "configuration_ready": False,
            "configuration_check": {
                "ready": False,
                "status": "missing_required_env",
                "fallback_reason": "missing_browser_render_token",
                "missing_env_keys": ["COMPANY_FILING_BROWSER_RENDER_TOKEN"],
            },
            "provider_capability": {
                "tier": "managed_unlocker",
                "captcha_unlocker": True,
            },
        },
        playwright_configured=False,
        proxy_count=0,
    )

    assert policy["unlocker_provider_ready"] is False
    assert policy["captcha_challenge_ready"] is False
    assert policy["configuration_ready"] is False
    assert policy["configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_BROWSER_RENDER_TOKEN"
    ]
    assert policy["fallback_reason"] == "missing_browser_render_token"
