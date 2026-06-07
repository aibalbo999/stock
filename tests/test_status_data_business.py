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
        matrix["data_business_logic"]["market_data_cache"]["evidence"][
            "latest_only_source_marker"
        ]
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
    assert report_retention["evidence"]["repository_latest_by_topic_available"] is True
    assert report_retention["evidence"]["repository_latest_tie_breaks_by_id"] is True
    assert report_retention["evidence"]["list_reports_uses_latest_by_topic"] is True
    assert report_retention["evidence"]["quality_summary_uses_latest_by_topic"] is True
    assert report_retention["evidence"]["maintenance_prunes_db_by_topic"] is True
    assert report_retention["evidence"]["maintenance_prunes_markdown_by_topic"] is True
    assert report_retention["evidence"]["run_links_cleared_for_pruned_reports"] is True

    assert matrix["data_business_logic"]["company_filing_fetch_hardening"]["status"] == "ready"
    filing_hardening = matrix["data_business_logic"]["company_filing_fetch_hardening"]["evidence"]
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
    assert filing_hardening["structured_api_configured"] is False
    assert "browser_render_runtime" in filing_hardening
    assert filing_hardening["playwright_render_enabled"] is True
    assert (
        filing_hardening["playwright_render_configured"]
        is status["company_filings"]["playwright_render_configured"]
    )
    assert "playwright_render_runtime" in filing_hardening
    assert "pdf_parser_dependencies" in filing_hardening

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
    assert pdf_parser_runtime["evidence"]["pdf_table_parser_available"] is status[
        "company_filings"
    ]["pdf_table_parser_available"]

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
    assert "browser_render_runtime" in filing_fallback["evidence"]
    assert (
        filing_fallback["evidence"]["playwright_render_configured"]
        is status["company_filings"]["playwright_render_configured"]
    )
    assert "playwright_render_runtime" in filing_fallback["evidence"]

    structured_api = matrix["data_business_logic"]["company_filing_structured_api_fallback"]
    assert structured_api["status"] == "not_configured"
    assert structured_api["evidence"]["configured"] is False
    assert (
        structured_api["evidence"]["runtime"]["fallback_reason"]
        == "missing_structured_api_provider_or_url"
    )
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
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "ready"


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
    assert "missing_browser_binary:chromium" in fallback["evidence"]["playwright_render_runtime"][
        "fallback_reason"
    ]
