from pathlib import Path

from app.core.config import get_settings
from app.services.service_status import service_status


def test_data_business_capability_matrix_shape_and_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    report_retention_source = Path("app/services/status_report_retention.py").read_text()
    matrix = status["upgrade_capability_matrix"]

    assert matrix["data_business_logic"]["market_data_cache"]["evidence"]["enabled"] is True
    assert (
        matrix["data_business_logic"]["market_data_cache"]["evidence"]["latest_only_source_marker"]
        == "latest-only"
    )
    market_fallback = matrix["data_business_logic"]["market_data_provider_fallback"]
    market_fallback_evidence = market_fallback["evidence"]
    assert "finmind_authenticated" in market_fallback_evidence
    assert "finmind_public_fallback_enabled" in market_fallback_evidence
    assert market_fallback_evidence["finmind_data_access_ready"] is True
    assert "fugle_price_fallback_configured" in market_fallback_evidence
    assert market_fallback_evidence["official_openapi_fallback_enabled"] is True
    assert "latest_monthly_revenue" in market_fallback_evidence["official_openapi_fallback_scope"]
    assert (
        "five_year_financial_metrics"
        in market_fallback_evidence["full_history_datasets_requiring_finmind"]
    )
    assert (
        "latest_quarter_income_balance"
        in market_fallback_evidence["official_openapi_latest_only_datasets"]
    )
    expected_market_status = "ready" if market_fallback_evidence["ready"] else "degraded"
    assert market_fallback["status"] == expected_market_status
    assert (
        status["market_data_cache"]["provider_matrix"]["price_history"]["fallback_configured"]
        is market_fallback_evidence["fugle_price_fallback_configured"]
    )

    report_retention = matrix["data_business_logic"]["latest_report_retention"]
    assert report_retention["status"] == "ready"
    assert status["report_retention"]["policy"] == "latest_per_topic"
    assert status["report_retention"]["collector_path"] == "app/services/status_report_retention.py"
    assert "from app.services.status_report_retention import (" in service_status_source
    assert "def _report_retention_status(" not in service_status_source
    assert "def report_retention_status(" in report_retention_source
    assert report_retention["evidence"]["write_prunes_db_by_topic"] is True
    assert report_retention["evidence"]["write_prunes_markdown_by_topic"] is True
    assert report_retention["evidence"]["write_prunes_report_artifacts_by_topic"] is True
    assert report_retention["evidence"]["repository_latest_by_topic_available"] is True
    assert report_retention["evidence"]["repository_latest_tie_breaks_by_id"] is True
    assert report_retention["evidence"]["list_reports_uses_latest_by_topic"] is True
    assert report_retention["evidence"]["quality_summary_uses_latest_by_topic"] is True
    assert report_retention["evidence"]["maintenance_prunes_db_by_topic"] is True
    assert report_retention["evidence"]["maintenance_prunes_markdown_by_topic"] is True
    assert report_retention["evidence"]["maintenance_prunes_report_artifacts_by_topic"] is True
    assert report_retention["evidence"]["run_links_cleared_for_pruned_reports"] is True
    assert report_retention["evidence"]["run_output_paths_cleared_for_pruned_reports"] is True
    assert report_retention["evidence"]["delete_before_clears_run_links"] is True
    assert report_retention["evidence"]["orphan_cleanup_clears_output_path"] is True
    assert report_retention["evidence"]["manual_delete_clears_run_links"] is True
    assert report_retention["evidence"]["manual_delete_prunes_markdown"] is True
    assert report_retention["evidence"]["manual_delete_prunes_report_artifacts"] is True
    assert report_retention["evidence"]["manual_delete_markdown_guardrail"] is True
    assert report_retention["evidence"]["manual_delete_artifact_guardrail"] is True
    assert report_retention["evidence"]["markdown_retention_smoke_passed"] is True
    assert report_retention["evidence"]["report_artifact_retention_smoke_passed"] is True
    markdown_smoke = report_retention["evidence"]["markdown_retention_smoke"]
    assert markdown_smoke["passed"] is True
    assert markdown_smoke["deleted_count"] == 5
    assert markdown_smoke["kept_files"] == [
        "20260607_080000_AI_topic.html",
        "20260607_080000_AI_topic.md",
        "20260607_080000_AI_topic.pdf",
        "20260607_090000_robot_topic.html",
        "20260607_090000_robot_topic.md",
        "single_report.html",
        "single_report.md",
    ]
    assert all(markdown_smoke["checks"].values())
    artifact_smoke = report_retention["evidence"]["report_artifact_retention_smoke"]
    assert artifact_smoke == markdown_smoke

    assert matrix["data_business_logic"]["company_filing_fetch_hardening"]["status"] == "ready"
    filing_hardening = matrix["data_business_logic"]["company_filing_fetch_hardening"]["evidence"]
    assert filing_hardening["capability_builder_path"] == (
        "app/services/status_capability_data_business_filings.py"
    )
    assert filing_hardening["effective_user_agent_count"] >= 1
    assert filing_hardening["anti_crawl_identity_enabled"] is True
    assert filing_hardening["user_agent_retry_rotation_enabled"] is True
    assert filing_hardening["proxy_retry_rotation_enabled"] is False
    assert filing_hardening["identity_retry_rotation_enabled"] is True
    assert (
        filing_hardening["browser_or_proxy_fallback_configured"]
        is status["company_filings"]["browser_or_proxy_fallback_configured"]
    )
    assert filing_hardening["browser_render_provider"] == "browserless"
    assert filing_hardening["browser_render_provider_capability"]["tier"] == "browser_render"
    assert (
        filing_hardening["browser_render_configuration_ready"]
        is status["company_filings"]["browser_render_configuration_ready"]
    )
    assert (
        filing_hardening["browser_render_configuration_check"]
        == status["company_filings"]["browser_render_configuration_check"]
    )
    assert filing_hardening["browser_render_token_required"] is False
    assert filing_hardening["browser_render_token_configured"] is False
    assert filing_hardening["high_risk_source_policy"]["configured_provider"] == "browserless"
    assert filing_hardening["high_risk_captcha_unlocker_ready"] is False
    assert filing_hardening["structured_api_configured"] is False
    assert "browser_render_runtime" in filing_hardening
    assert filing_hardening["playwright_render_enabled"] is True
    assert (
        filing_hardening["playwright_render_configured"]
        is status["company_filings"]["playwright_render_configured"]
    )
    assert "playwright_render_runtime" in filing_hardening
    assert "pdf_parser_dependencies" in filing_hardening

    render_contract = matrix["data_business_logic"]["company_filing_render_provider_contract"]
    assert render_contract["status"] == "ready"
    assert render_contract["evidence"]["ready"] is True
    assert render_contract["evidence"]["contract"]["provider_count"] == 5
    assert render_contract["evidence"]["smoke_cli"].endswith(
        "scripts/company_filing_render_smoke.py --provider-contract --json"
    )

    high_risk_unlocker = matrix["data_business_logic"]["company_filing_high_risk_unlocker"]
    expected_high_risk_unlocker_status = (
        "ready"
        if status["company_filings"]["high_risk_captcha_unlocker_ready"]
        else "not_configured"
    )
    assert high_risk_unlocker["status"] == expected_high_risk_unlocker_status
    assert "mops.twse.com.tw" in high_risk_unlocker["evidence"]["domains"]
    assert "flaresolverr" in high_risk_unlocker["evidence"]["recommended_unlocker_providers"]
    assert (
        high_risk_unlocker["evidence"]["configuration_check"]
        == status["company_filings"]["browser_render_configuration_check"]
    )
    assert high_risk_unlocker["evidence"]["compose_env_override_ready"] is True
    assert (
        "COMPANY_FILING_BROWSER_RENDER_URL=http://flaresolverr:8191/v1"
        in high_risk_unlocker["evidence"]["compose_recommended_env"]
    )
    assert (
        high_risk_unlocker["evidence"]["fallback_reason"]
        == status["company_filings"]["high_risk_source_policy"]["fallback_reason"]
    )

    pdf_parser_runtime = matrix["data_business_logic"]["company_filing_pdf_table_parser_runtime"]
    expected_pdf_runtime_status = (
        "ready"
        if (
            not status["company_filings"]["pdf_extract_tables"]
            or status["company_filings"]["pdf_table_extraction_runtime_available"]
        )
        else "not_configured"
    )
    assert pdf_parser_runtime["status"] == expected_pdf_runtime_status
    assert (
        pdf_parser_runtime["evidence"]["pdf_table_parser_available"]
        is status["company_filings"]["pdf_table_parser_available"]
    )

    filing_fallback = matrix["data_business_logic"]["company_filing_browser_or_proxy_fallback"]
    expected_filing_fallback_status = (
        "ready"
        if status["company_filings"]["browser_or_proxy_fallback_configured"]
        else "not_configured"
    )
    assert filing_fallback["status"] == expected_filing_fallback_status
    assert (
        filing_fallback["evidence"]["browser_or_proxy_fallback_configured"]
        is status["company_filings"]["browser_or_proxy_fallback_configured"]
    )
    assert filing_fallback["evidence"]["proxy_count"] == 0
    assert filing_fallback["evidence"]["browser_render_configured"] is False
    assert filing_fallback["evidence"]["browser_render_provider"] == "browserless"
    assert (
        filing_fallback["evidence"]["browser_render_configuration_check"]
        == status["company_filings"]["browser_render_configuration_check"]
    )
    assert filing_fallback["evidence"]["browser_render_token_required"] is False
    assert (
        filing_fallback["evidence"]["high_risk_captcha_unlocker_ready"]
        is status["company_filings"]["high_risk_captcha_unlocker_ready"]
    )
    assert "browser_render_runtime" in filing_fallback["evidence"]
    assert (
        filing_fallback["evidence"]["playwright_render_configured"]
        is status["company_filings"]["playwright_render_configured"]
    )
    assert "playwright_render_runtime" in filing_fallback["evidence"]

    structured_api = matrix["data_business_logic"]["company_filing_structured_api_fallback"]
    assert structured_api["status"] == "not_configured"
    assert structured_api["evidence"]["configured"] is False
    assert structured_api["evidence"]["configuration_ready"] is False
    assert structured_api["evidence"]["configuration_check"]["status"] == "missing_required_env"
    assert structured_api["evidence"]["configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
    ]
    assert structured_api["evidence"]["provider_profile_key"] == "custom"
    assert structured_api["evidence"]["request_contract"]["method"] == "GET"
    assert structured_api["evidence"]["retry_policy"]["attempts"] >= 1
    assert "documents" in structured_api["evidence"]["response_row_aliases"]
    assert "ticker_or_company_mention" in structured_api["evidence"]["required_document_fields"]
    assert "scrapingbee_dataset" in structured_api["evidence"]["supported_provider_examples"]
    assert (
        structured_api["evidence"]["runtime"]["fallback_reason"]
        == "missing_structured_api_provider_or_url"
    )
    assert (
        "structured_company_filing_sample.json"
        in structured_api["evidence"]["runtime"]["sample_contract_cli"]
    )
    assert structured_api["evidence"]["runtime"]["sample_contract_ready"] is True
    assert structured_api["evidence"]["runtime"]["sample_contract"]["status"] == "ready"
    assert structured_api["evidence"]["runtime"]["sample_contract"]["document_count"] >= 1

    structured_sample_contract = matrix["data_business_logic"][
        "company_filing_structured_api_sample_contract"
    ]
    assert structured_sample_contract["status"] == "ready"
    assert structured_sample_contract["evidence"]["ready"] is True
    assert (
        "structured_company_filing_sample.json"
        in structured_sample_contract["evidence"]["smoke_cli"]
    )
    assert structured_sample_contract["evidence"]["contract"]["status"] == "ready"
    assert structured_sample_contract["evidence"]["contract"]["document_count"] >= 1
    assert matrix["data_business_logic"]["source_quality_weighting"]["status"] == "ready"


def test_company_filing_playwright_fallback_requires_available_dependency(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_playwright_browser_status",
        lambda browser: {
            "browser": browser,
            "dependency_available": False,
            "browser_available": False,
            "fallback_reason": "missing_dependency:playwright",
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_dependency_available"] is False
    assert status["company_filings"]["playwright_render_browser_available"] is False
    assert status["company_filings"]["playwright_render_configured"] is False
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is False
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "not_configured"


def test_structured_api_capability_requires_token_for_paid_provider(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_PROVIDER", "tej")
    monkeypatch.setenv("COMPANY_FILING_STRUCTURED_API_URL", "https://api.tej.example/filings")
    monkeypatch.delenv("COMPANY_FILING_STRUCTURED_API_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["structured_api_configured"] is True
    assert status["company_filings"]["structured_api_configuration_ready"] is False
    assert status["company_filings"]["structured_api_configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_STRUCTURED_API_TOKEN"
    ]
    structured_api = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_structured_api_fallback"
    ]
    assert structured_api["status"] == "not_configured"
    assert structured_api["evidence"]["configuration_ready"] is False
    assert structured_api["evidence"]["configuration_check"]["fallback_reason"] == (
        "missing_structured_api_token"
    )


def test_company_filing_high_risk_unlocker_requires_managed_provider_token(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "scrapingbee")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "https://app.scrapingbee.com/api/v1")
    monkeypatch.delenv("COMPANY_FILING_BROWSER_RENDER_TOKEN", raising=False)
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    monkeypatch.setenv("COMPANY_FILING_PROXY_URLS", "")
    get_settings.cache_clear()
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    company_filings = status["company_filings"]
    assert company_filings["browser_render_provider"] == "scrapingbee"
    assert company_filings["browser_render_configuration_ready"] is False
    assert company_filings["browser_render_token_required"] is True
    assert company_filings["browser_render_token_configured"] is False
    assert company_filings["browser_render_runtime"]["connection_checked"] is False
    assert company_filings["browser_render_runtime"]["fallback_reason"] == (
        "missing_browser_render_token"
    )
    assert company_filings["high_risk_captcha_unlocker_ready"] is False
    assert company_filings["high_risk_source_policy"]["fallback_reason"] == (
        "missing_browser_render_token"
    )
    high_risk_unlocker = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_high_risk_unlocker"
    ]
    assert high_risk_unlocker["status"] == "not_configured"
    assert high_risk_unlocker["evidence"]["configuration_ready"] is False
    assert high_risk_unlocker["evidence"]["configuration_check"]["missing_env_keys"] == [
        "COMPANY_FILING_BROWSER_RENDER_TOKEN"
    ]


def test_company_filing_playwright_fallback_ready_when_browser_available(monkeypatch) -> None:
    monkeypatch.delenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_playwright_browser_status",
        lambda browser: {
            "browser": browser,
            "dependency_available": True,
            "browser_available": True,
            "browser_executable_exists": True,
            "executable_path": "/tmp/chromium",
            "fallback_reason": None,
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_dependency_available"] is True
    assert status["company_filings"]["playwright_render_browser_available"] is True
    assert status["company_filings"]["playwright_render_configured"] is True
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is True
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "ready"


def test_company_filing_browser_render_fallback_requires_reachable_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "http://127.0.0.1:3000/content")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_browser_render_status",
        lambda: {
            "enabled": True,
            "url_configured": True,
            "endpoint": "http://127.0.0.1:3000/content",
            "connection_checked": True,
            "endpoint_reachable": False,
            "runtime_available": False,
            "fallback_reason": "browser_render_endpoint_unreachable:ConnectionRefusedError",
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["browser_render_enabled"] is True
    assert status["company_filings"]["browser_render_url_configured"] is True
    assert status["company_filings"]["browser_render_endpoint_reachable"] is False
    assert status["company_filings"]["browser_render_configured"] is False
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is False
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "not_configured"
    assert (
        fallback["evidence"]["browser_render_runtime"]["fallback_reason"]
        == "browser_render_endpoint_unreachable:ConnectionRefusedError"
    )


def test_company_filing_browser_render_fallback_ready_when_endpoint_reachable(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "http://127.0.0.1:3000/content")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_browser_render_status",
        lambda: {
            "enabled": True,
            "url_configured": True,
            "endpoint": "http://127.0.0.1:3000/content",
            "connection_checked": True,
            "endpoint_reachable": True,
            "runtime_available": True,
            "fallback_reason": None,
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["browser_render_enabled"] is True
    assert status["company_filings"]["browser_render_configured"] is True
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is True
    assert status["company_filings"]["high_risk_captcha_unlocker_ready"] is False
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "ready"


def test_company_filing_high_risk_unlocker_ready_with_flaresolverr(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "flaresolverr")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "http://127.0.0.1:8191/v1")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_browser_render_status",
        lambda: {
            "enabled": True,
            "provider": "flaresolverr",
            "provider_capability": {
                "provider": "flaresolverr",
                "tier": "unlocker",
                "captcha_unlocker": True,
            },
            "url_configured": True,
            "endpoint": "http://127.0.0.1:8191/v1",
            "connection_checked": True,
            "endpoint_reachable": True,
            "runtime_available": True,
            "high_risk_runtime_available": True,
            "fallback_reason": None,
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["high_risk_captcha_unlocker_ready"] is True
    assert status["company_filings"]["high_risk_source_mitigation_ready"] is True
    high_risk_unlocker = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_high_risk_unlocker"
    ]
    assert high_risk_unlocker["status"] == "ready"
    assert high_risk_unlocker["evidence"]["configured_provider"] == "flaresolverr"


def test_company_filing_playwright_fallback_requires_browser_binary(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_playwright_browser_status",
        lambda browser: {
            "browser": browser,
            "dependency_available": True,
            "browser_available": False,
            "browser_executable_exists": False,
            "fallback_reason": f"missing_browser_binary:{browser}; run python -m playwright install {browser}",
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_dependency_available"] is True
    assert status["company_filings"]["playwright_render_browser_available"] is False
    assert status["company_filings"]["playwright_render_configured"] is False
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is False
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "not_configured"
    assert (
        "missing_browser_binary:chromium"
        in fallback["evidence"]["playwright_render_runtime"]["fallback_reason"]
    )
