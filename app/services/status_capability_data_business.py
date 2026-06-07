from __future__ import annotations

from app.services.status_capability_helpers import capability as _capability
from app.services.status_market_data import _market_data_provider_readiness


def data_business_capabilities(
    *,
    market_cache_status: dict,
    finmind_status: dict,
    fugle_status: dict,
    company_filing_status: dict,
    report_retention_status: dict,
    candidate_confidence_status: dict,
) -> dict:
    market_provider_readiness = _market_data_provider_readiness(
        market_cache_status,
        finmind_status,
        fugle_status,
    )

    return {
        "market_data_cache": _capability(
            "ready" if market_cache_status.get("available") else "degraded",
            evidence={
                "enabled": market_cache_status.get("enabled"),
                "available": market_cache_status.get("available"),
                "backend": market_cache_status.get("backend"),
                "stale_rescue_enabled": market_cache_status.get("stale_rescue_enabled"),
                "latest_only_source_marker": market_cache_status.get("latest_only_source_marker"),
                "financial_metrics_ttl_seconds": market_cache_status.get(
                    "financial_metrics_ttl_seconds"
                ),
                "valuation_metrics_ttl_seconds": market_cache_status.get(
                    "valuation_metrics_ttl_seconds"
                ),
            },
        ),
        "market_data_provider_fallback": _capability(
            "ready" if market_provider_readiness.get("ready") else "degraded",
            evidence={
                "price_provider_order": market_cache_status.get("price_provider_order"),
                "provider_matrix": market_cache_status.get("provider_matrix"),
                "fugle_configured": fugle_status.get("configured"),
                "finmind_configured": finmind_status.get("configured"),
                **market_provider_readiness,
            },
        ),
        "latest_report_retention": _capability(
            "ready"
            if report_retention_status.get("write_prunes_db_by_topic")
            and report_retention_status.get("write_prunes_markdown_by_topic")
            and report_retention_status.get("list_reports_uses_latest_by_topic")
            and report_retention_status.get("quality_summary_uses_latest_by_topic")
            and report_retention_status.get("maintenance_prunes_db_by_topic")
            and report_retention_status.get("maintenance_prunes_markdown_by_topic")
            and report_retention_status.get("run_links_cleared_for_pruned_reports")
            else "degraded",
            evidence=report_retention_status,
            detail=(
                "Generated reports use latest-per-topic retention across DB writes, "
                "report center queries, quality summary, maintenance cleanup, and markdown files."
            ),
        ),
        "company_filing_fetch_hardening": _capability(
            "ready"
            if company_filing_status.get("anti_crawl_identity_enabled")
            and company_filing_status.get("http_retries", 0) > 0
            and company_filing_status.get("html_extract_tables")
            else "degraded",
            evidence={
                "custom_user_agent_count": company_filing_status.get("custom_user_agent_count"),
                "default_user_agent_count": company_filing_status.get("default_user_agent_count"),
                "effective_user_agent_count": company_filing_status.get(
                    "effective_user_agent_count"
                ),
                "user_agent_mode": company_filing_status.get("user_agent_mode"),
                "anti_crawl_identity_enabled": company_filing_status.get(
                    "anti_crawl_identity_enabled"
                ),
                "proxy_count": company_filing_status.get("proxy_count"),
                "user_agent_retry_rotation_enabled": company_filing_status.get(
                    "user_agent_retry_rotation_enabled"
                ),
                "proxy_retry_rotation_enabled": company_filing_status.get(
                    "proxy_retry_rotation_enabled"
                ),
                "identity_retry_rotation_enabled": company_filing_status.get(
                    "identity_retry_rotation_enabled"
                ),
                "browser_or_proxy_fallback_configured": company_filing_status.get(
                    "browser_or_proxy_fallback_configured"
                ),
                "structured_api_configured": company_filing_status.get(
                    "structured_api_configured"
                ),
                "structured_api_provider": company_filing_status.get("structured_api_provider"),
                "http_retries": company_filing_status.get("http_retries"),
                "retryable_http_statuses": company_filing_status.get("retryable_http_statuses"),
                "pdf_parser": company_filing_status.get("pdf_parser"),
                "pdf_extract_tables": company_filing_status.get("pdf_extract_tables"),
                "pdf_parser_available": company_filing_status.get("pdf_parser_available"),
                "pdf_parser_dependencies": company_filing_status.get("pdf_parser_dependencies"),
                "html_extract_tables": company_filing_status.get("html_extract_tables"),
                "browser_render_configured": company_filing_status.get(
                    "browser_render_configured"
                ),
                "browser_render_provider": company_filing_status.get("browser_render_provider"),
                "browser_render_supported_providers": company_filing_status.get(
                    "browser_render_supported_providers"
                ),
                "browser_render_url_configured": company_filing_status.get(
                    "browser_render_url_configured"
                ),
                "browser_render_endpoint_reachable": company_filing_status.get(
                    "browser_render_endpoint_reachable"
                ),
                "browser_render_runtime": company_filing_status.get("browser_render_runtime"),
                "playwright_render_enabled": company_filing_status.get(
                    "playwright_render_enabled"
                ),
                "playwright_render_dependency_available": company_filing_status.get(
                    "playwright_render_dependency_available"
                ),
                "playwright_render_browser_available": company_filing_status.get(
                    "playwright_render_browser_available"
                ),
                "playwright_render_runtime": company_filing_status.get(
                    "playwright_render_runtime"
                ),
                "playwright_render_configured": company_filing_status.get(
                    "playwright_render_configured"
                ),
            },
        ),
        "company_filing_pdf_table_parser_runtime": _capability(
            "ready"
            if (
                not company_filing_status.get("pdf_extract_tables")
                or company_filing_status.get("pdf_table_extraction_runtime_available")
            )
            else "not_configured",
            evidence={
                "pdf_parser": company_filing_status.get("pdf_parser"),
                "pdf_extract_tables": company_filing_status.get("pdf_extract_tables"),
                "pdf_parser_available": company_filing_status.get("pdf_parser_available"),
                "pdf_table_parser_available": company_filing_status.get(
                    "pdf_table_parser_available"
                ),
                "pdf_table_extraction_runtime_available": company_filing_status.get(
                    "pdf_table_extraction_runtime_available"
                ),
                "pdf_parser_dependencies": company_filing_status.get("pdf_parser_dependencies"),
            },
            detail=(
                "Deployment runtime check for table-capable PDF parsers. "
                "When PDF table extraction is enabled, pdfplumber or unstructured[pdf] must be importable."
            ),
        ),
        "company_filing_browser_or_proxy_fallback": _capability(
            "ready"
            if company_filing_status.get("browser_or_proxy_fallback_configured")
            else "not_configured",
            evidence={
                "browser_or_proxy_fallback_configured": company_filing_status.get(
                    "browser_or_proxy_fallback_configured"
                ),
                "proxy_count": company_filing_status.get("proxy_count"),
                "browser_render_enabled": company_filing_status.get("browser_render_enabled"),
                "browser_render_configured": company_filing_status.get(
                    "browser_render_configured"
                ),
                "browser_render_provider": company_filing_status.get("browser_render_provider"),
                "browser_render_supported_providers": company_filing_status.get(
                    "browser_render_supported_providers"
                ),
                "browser_render_url_configured": company_filing_status.get(
                    "browser_render_url_configured"
                ),
                "browser_render_endpoint_reachable": company_filing_status.get(
                    "browser_render_endpoint_reachable"
                ),
                "browser_render_runtime": company_filing_status.get("browser_render_runtime"),
                "browser_render_timeout_seconds": company_filing_status.get(
                    "browser_render_timeout_seconds"
                ),
                "playwright_render_enabled": company_filing_status.get(
                    "playwright_render_enabled"
                ),
                "playwright_render_dependency_available": company_filing_status.get(
                    "playwright_render_dependency_available"
                ),
                "playwright_render_browser_available": company_filing_status.get(
                    "playwright_render_browser_available"
                ),
                "playwright_render_runtime": company_filing_status.get(
                    "playwright_render_runtime"
                ),
                "playwright_render_configured": company_filing_status.get(
                    "playwright_render_configured"
                ),
                "playwright_render_browser": company_filing_status.get(
                    "playwright_render_browser"
                ),
                "playwright_render_wait_until": company_filing_status.get(
                    "playwright_render_wait_until"
                ),
                "playwright_render_timeout_seconds": company_filing_status.get(
                    "playwright_render_timeout_seconds"
                ),
            },
            detail=(
                "Optional deployment hardening for blocked, placeholder, or dynamic filing pages. "
                "Core fetch remains usable through browser-like User-Agent rotation and retries."
            ),
        ),
        "company_filing_structured_api_fallback": _capability(
            "ready"
            if company_filing_status.get("structured_api_configured")
            else "not_configured",
            evidence={
                "configured": company_filing_status.get("structured_api_configured"),
                "provider": company_filing_status.get("structured_api_provider"),
                "url_configured": company_filing_status.get("structured_api_url_configured"),
                "token_configured": company_filing_status.get("structured_api_token_configured"),
                "provider_profile_key": (
                    company_filing_status.get("structured_api_runtime") or {}
                ).get("provider_profile_key"),
                "request_contract": (
                    company_filing_status.get("structured_api_runtime") or {}
                ).get("request_contract"),
                "retry_policy": (
                    company_filing_status.get("structured_api_runtime") or {}
                ).get("retry_policy"),
                "response_row_aliases": (
                    company_filing_status.get("structured_api_runtime") or {}
                ).get("response_row_aliases"),
                "required_document_fields": (
                    company_filing_status.get("structured_api_runtime") or {}
                ).get("required_document_fields"),
                "supported_provider_examples": (
                    company_filing_status.get("structured_api_runtime") or {}
                ).get("supported_provider_examples"),
                "runtime": company_filing_status.get("structured_api_runtime"),
            },
            detail=(
                "Optional paid/professional company filing source for investor presentations, "
                "material information, and hard-to-scrape MOPS disclosures."
            ),
        ),
        "company_filing_cache": _capability(
            "ready" if company_filing_status.get("cache_available") else "degraded",
            evidence={
                "cache_enabled": company_filing_status.get("cache_enabled"),
                "cache_available": company_filing_status.get("cache_available"),
                "cache_backend": company_filing_status.get("cache_backend"),
                "cache_key_scope": company_filing_status.get("cache_key_scope"),
                "cache_ttl_seconds": company_filing_status.get("cache_ttl_seconds"),
            },
        ),
        "source_quality_weighting": _capability(
            "ready"
            if (candidate_confidence_status.get("source_credibility_weights") or {}).get(
                "investment_blog", 1.0
            )
            < 0.75
            else "degraded",
            evidence={
                "promotion_rule": candidate_confidence_status.get("promotion_rule"),
                "source_credibility_weights": candidate_confidence_status.get(
                    "source_credibility_weights"
                ),
            },
        ),
    }
