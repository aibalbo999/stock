from __future__ import annotations

from importlib.util import find_spec
from typing import Callable

from app.data_sources.company_filings import (
    COMPANY_FILING_RETRYABLE_HTTP_STATUSES,
    DEFAULT_COMPANY_FILING_USER_AGENTS,
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
    company_filing_structured_api_status,
)
from app.services.company_filing_cache import RedisCompanyFilingCache


def company_filing_status(
    settings,
    *,
    redis_status: dict,
    visual_rag_runtime: dict,
    module_available: Callable[[str], bool] = None,
    browser_render_status_func: Callable[[], dict] = company_filing_browser_render_status,
    playwright_browser_status_func: Callable[[str | None], dict] = company_filing_playwright_browser_status,
    structured_api_status_func: Callable[[], dict] = company_filing_structured_api_status,
) -> dict:
    module_available = module_available or _module_available
    user_agent_status = _company_filing_user_agent_status(
        settings.company_filing_user_agents
    )
    proxy_count = len(_split_config_values(settings.company_filing_proxy_urls))
    pdf_parser_status = _company_filing_pdf_parser_status(
        settings.company_filing_pdf_parser,
        extract_tables=settings.company_filing_pdf_extract_tables,
        module_available=module_available,
    )
    user_agent_count = int(user_agent_status.get("effective_user_agent_count") or 0)
    browser_render_runtime = browser_render_status_func()
    browser_render_configured = bool(
        browser_render_runtime.get("runtime_available")
    )
    playwright_runtime = playwright_browser_status_func(
        settings.company_filing_playwright_browser
    )
    playwright_dependency_available = bool(
        playwright_runtime.get("dependency_available")
    )
    playwright_browser_available = bool(
        playwright_runtime.get("browser_available")
    )
    playwright_configured = bool(
        settings.company_filing_playwright_render_enabled
        and playwright_browser_available
    )
    structured_api_runtime = structured_api_status_func()
    return {
        "collector_path": "app/services/status_company_filings.py",
        **user_agent_status,
        "proxy_count": proxy_count,
        "user_agent_retry_rotation_enabled": user_agent_count > 1,
        "proxy_retry_rotation_enabled": proxy_count > 1,
        "identity_retry_rotation_enabled": (
            user_agent_count > 1 or proxy_count > 1
        ),
        "http_retries": max(0, int(settings.company_filing_http_retries)),
        "retryable_http_statuses": sorted(COMPANY_FILING_RETRYABLE_HTTP_STATUSES),
        "base_retry_delay_seconds": max(0.0, float(settings.company_filing_base_retry_delay_seconds)),
        "max_retry_delay_seconds": max(0.0, float(settings.company_filing_max_retry_delay_seconds)),
        "pdf_parser": settings.company_filing_pdf_parser,
        "pdf_extract_tables": settings.company_filing_pdf_extract_tables,
        "pdf_parser_dependencies": pdf_parser_status,
        "pdf_parser_available": pdf_parser_status.get("configured_parser_available"),
        "pdf_table_parser_available": pdf_parser_status.get("table_parser_available"),
        "pdf_table_extraction_runtime_available": pdf_parser_status.get(
            "table_extraction_runtime_available"
        ),
        "html_extract_tables": settings.company_filing_html_extract_tables,
        "cache_enabled": settings.company_filing_cache_enabled,
        "cache_available": bool(settings.company_filing_cache_enabled and redis_status.get("ok")),
        "cache_backend": "redis",
        "cache_key_namespace": RedisCompanyFilingCache.KEY_NAMESPACE,
        "cache_key_scope": ["url", "parser", "extract_tables", "html_extract_tables"],
        "cache_ttl_seconds": settings.company_filing_cache_ttl_seconds,
        "browser_render_enabled": settings.company_filing_browser_render_enabled,
        "browser_render_provider": browser_render_runtime.get("provider"),
        "browser_render_supported_providers": browser_render_runtime.get(
            "supported_providers"
        ),
        "browser_render_url_configured": browser_render_runtime.get("url_configured"),
        "browser_render_endpoint_reachable": browser_render_runtime.get(
            "endpoint_reachable"
        ),
        "browser_render_runtime": browser_render_runtime,
        "browser_render_configured": browser_render_configured,
        "browser_render_concurrency": max(
            1,
            int(settings.company_filing_browser_render_concurrency),
        ),
        "playwright_render_enabled": settings.company_filing_playwright_render_enabled,
        "playwright_render_dependency_available": playwright_dependency_available,
        "playwright_render_browser_available": playwright_browser_available,
        "playwright_render_runtime": playwright_runtime,
        "playwright_render_configured": playwright_configured,
        "playwright_render_browser": settings.company_filing_playwright_browser,
        "playwright_render_wait_until": settings.company_filing_playwright_wait_until,
        "playwright_render_timeout_seconds": settings.company_filing_playwright_timeout_seconds,
        "browser_or_proxy_fallback_configured": bool(
            browser_render_configured
            or playwright_configured
            or _split_config_values(settings.company_filing_proxy_urls)
        ),
        "browser_render_timeout_seconds": settings.company_filing_browser_render_timeout_seconds,
        "structured_api_configured": structured_api_runtime.get("configured"),
        "structured_api_provider": structured_api_runtime.get("provider"),
        "structured_api_url_configured": structured_api_runtime.get(
            "url_configured"
        ),
        "structured_api_token_configured": structured_api_runtime.get(
            "token_configured"
        ),
        "structured_api_runtime": structured_api_runtime,
        "visual_rag_enabled": visual_rag_runtime.get("enabled"),
        "visual_rag_mode": visual_rag_runtime.get("mode"),
        "visual_rag_mode_supported": visual_rag_runtime.get("mode_supported"),
        "visual_rag_runtime_available": visual_rag_runtime.get("runtime_available"),
        "visual_rag_renderer_dependency_available": visual_rag_runtime.get(
            "renderer_dependency_available"
        ),
        "visual_rag_model": visual_rag_runtime.get("model"),
        "visual_rag_model_supported": visual_rag_runtime.get("model_supported"),
        "visual_rag_fallback_reason": visual_rag_runtime.get("fallback_reason"),
        "visual_rag_max_pages": visual_rag_runtime.get("max_pages"),
        "visual_rag_dpi": visual_rag_runtime.get("dpi"),
        "visual_rag_runtime": visual_rag_runtime,
    }


def _company_filing_user_agent_status(configured_value: str) -> dict:
    configured = _split_config_values(configured_value)
    default_count = len(DEFAULT_COMPANY_FILING_USER_AGENTS)
    effective_count = len(configured) if configured else default_count
    return {
        "custom_user_agent_count": len(configured),
        "default_user_agent_count": default_count,
        "effective_user_agent_count": effective_count,
        "user_agent_mode": "custom" if configured else "default_browser_like",
        "anti_crawl_identity_enabled": effective_count > 0,
    }


def _company_filing_pdf_parser_status(
    parser: str,
    *,
    extract_tables: bool,
    module_available: Callable[[str], bool] = None,
) -> dict:
    module_available = module_available or _module_available
    normalized_parser = str(parser or "auto").strip().lower() or "auto"
    pdfplumber_available = module_available("pdfplumber")
    unstructured_pdf_available = module_available("unstructured.partition.pdf")
    pypdf_available = module_available("pypdf")
    parser_availability = {
        "pdfplumber": pdfplumber_available,
        "unstructured": unstructured_pdf_available,
        "pypdf": pypdf_available,
    }
    if normalized_parser == "auto":
        configured_parser_available = any(parser_availability.values())
        resolved_parser_candidates = [
            name for name in ("pdfplumber", "unstructured", "pypdf") if parser_availability[name]
        ]
    else:
        configured_parser_available = bool(parser_availability.get(normalized_parser))
        resolved_parser_candidates = [normalized_parser] if configured_parser_available else []
    table_parser_available = bool(pdfplumber_available or unstructured_pdf_available)
    table_extraction_runtime_available = bool(extract_tables and table_parser_available)
    fallback_reason = (
        "missing_table_pdf_parser_dependency:pdfplumber_or_unstructured"
        if extract_tables and not table_parser_available
        else None
    )
    return {
        "configured_parser": normalized_parser,
        "configured_parser_available": configured_parser_available,
        "resolved_parser_candidates": resolved_parser_candidates,
        "pdfplumber_available": pdfplumber_available,
        "unstructured_pdf_available": unstructured_pdf_available,
        "pypdf_available": pypdf_available,
        "table_parser_available": table_parser_available,
        "table_extraction_requested": bool(extract_tables),
        "table_extraction_runtime_available": table_extraction_runtime_available,
        "fallback_reason": fallback_reason,
    }


def _split_config_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _module_available(module_name: str) -> bool:
    return find_spec(module_name) is not None
