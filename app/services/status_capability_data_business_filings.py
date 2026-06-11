from __future__ import annotations

from app.services.status_capability_helpers import capability as _capability


def company_filing_capabilities(*, company_filing_status: dict) -> dict:
    structured_api_runtime = company_filing_status.get("structured_api_runtime") or {}
    structured_sample_contract = structured_api_runtime.get("sample_contract") or {}
    structured_sample_diagnostics = structured_sample_contract.get("contract_diagnostics") or {}
    structured_sample_diagnostics_ready = bool(
        structured_sample_diagnostics.get("row_container")
        and structured_sample_diagnostics.get("field_coverage")
        and "conversion_ratio" in structured_sample_diagnostics
    )
    return {
        "company_filing_fetch_hardening": _capability(
            "ready"
            if company_filing_status.get("anti_crawl_identity_enabled")
            and company_filing_status.get("http_retries", 0) > 0
            and company_filing_status.get("html_extract_tables")
            else "degraded",
            evidence={
                "capability_builder_path": (
                    "app/services/status_capability_data_business_filings.py"
                ),
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
                "structured_api_configured": company_filing_status.get("structured_api_configured"),
                "structured_api_provider": company_filing_status.get("structured_api_provider"),
                "official_material_information_openapi_ready": company_filing_status.get(
                    "official_material_information_openapi_ready"
                ),
                "official_material_information_openapi_provider": company_filing_status.get(
                    "official_material_information_openapi_provider"
                ),
                "official_material_information_openapi_source_urls": company_filing_status.get(
                    "official_material_information_openapi_source_urls"
                ),
                "http_retries": company_filing_status.get("http_retries"),
                "retryable_http_statuses": company_filing_status.get("retryable_http_statuses"),
                "pdf_parser": company_filing_status.get("pdf_parser"),
                "pdf_extract_tables": company_filing_status.get("pdf_extract_tables"),
                "pdf_parser_available": company_filing_status.get("pdf_parser_available"),
                "pdf_parser_dependencies": company_filing_status.get("pdf_parser_dependencies"),
                "html_extract_tables": company_filing_status.get("html_extract_tables"),
                "browser_render_configured": company_filing_status.get("browser_render_configured"),
                "browser_render_provider": company_filing_status.get("browser_render_provider"),
                "browser_render_supported_providers": company_filing_status.get(
                    "browser_render_supported_providers"
                ),
                "browser_render_provider_capability": company_filing_status.get(
                    "browser_render_provider_capability"
                ),
                "browser_render_configuration_ready": company_filing_status.get(
                    "browser_render_configuration_ready"
                ),
                "browser_render_configuration_check": company_filing_status.get(
                    "browser_render_configuration_check"
                ),
                "browser_render_token_required": company_filing_status.get(
                    "browser_render_token_required"
                ),
                "browser_render_token_configured": company_filing_status.get(
                    "browser_render_token_configured"
                ),
                "high_risk_source_policy": company_filing_status.get("high_risk_source_policy"),
                "high_risk_source_mitigation_ready": company_filing_status.get(
                    "high_risk_source_mitigation_ready"
                ),
                "high_risk_captcha_unlocker_ready": company_filing_status.get(
                    "high_risk_captcha_unlocker_ready"
                ),
                "browser_render_url_configured": company_filing_status.get(
                    "browser_render_url_configured"
                ),
                "browser_render_endpoint_reachable": company_filing_status.get(
                    "browser_render_endpoint_reachable"
                ),
                "browser_render_runtime": company_filing_status.get("browser_render_runtime"),
                "playwright_render_enabled": company_filing_status.get("playwright_render_enabled"),
                "playwright_render_dependency_available": company_filing_status.get(
                    "playwright_render_dependency_available"
                ),
                "playwright_render_browser_available": company_filing_status.get(
                    "playwright_render_browser_available"
                ),
                "playwright_render_runtime": company_filing_status.get("playwright_render_runtime"),
                "playwright_render_configured": company_filing_status.get(
                    "playwright_render_configured"
                ),
            },
        ),
        "company_filing_high_risk_unlocker": _capability(
            "ready"
            if company_filing_status.get("high_risk_captcha_unlocker_ready")
            else "not_configured",
            evidence=company_filing_status.get("high_risk_source_policy") or {},
            detail=(
                "MOPS/TWSE/TPEx 高風險揭露來源若遇到 CAPTCHA/anti-bot，需使用 unlocker 等級提供者，"
                "例如 FlareSolverr、ScrapingBee 或 BrightData；Playwright/Browserless 仍是有用的"
                "瀏覽器渲染 fallback，但不計入 CAPTCHA unlocker。"
            ),
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
                "pdf_table_quality_provenance_enabled": company_filing_status.get(
                    "pdf_table_quality_provenance_enabled"
                ),
                "pdf_table_quality_provenance_prefix": company_filing_status.get(
                    "pdf_table_quality_provenance_prefix"
                ),
                "pdf_parser_dependencies": company_filing_status.get("pdf_parser_dependencies"),
            },
            detail=(
                "PDF 表格解析套件部署檢查；啟用 PDF 表格抽取時，"
                "pdfplumber 或 unstructured[pdf] 需可匯入。"
            ),
        ),
        "company_filing_render_provider_contract": _capability(
            "ready"
            if company_filing_status.get("browser_render_provider_contract_ready")
            else "degraded",
            evidence={
                "ready": company_filing_status.get("browser_render_provider_contract_ready"),
                "smoke_cli": company_filing_status.get(
                    "browser_render_provider_contract_smoke_cli"
                ),
                "contract": company_filing_status.get("browser_render_provider_contract"),
            },
            detail=(
                "離線提供者格式檢查，確認 Browserless、Generic、FlareSolverr、"
                "ScrapingBee 與 BrightData 的請求/回應對應。"
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
                "browser_render_configured": company_filing_status.get("browser_render_configured"),
                "browser_render_provider": company_filing_status.get("browser_render_provider"),
                "browser_render_supported_providers": company_filing_status.get(
                    "browser_render_supported_providers"
                ),
                "browser_render_provider_capability": company_filing_status.get(
                    "browser_render_provider_capability"
                ),
                "browser_render_configuration_ready": company_filing_status.get(
                    "browser_render_configuration_ready"
                ),
                "browser_render_configuration_check": company_filing_status.get(
                    "browser_render_configuration_check"
                ),
                "browser_render_token_required": company_filing_status.get(
                    "browser_render_token_required"
                ),
                "browser_render_token_configured": company_filing_status.get(
                    "browser_render_token_configured"
                ),
                "high_risk_source_policy": company_filing_status.get("high_risk_source_policy"),
                "high_risk_source_mitigation_ready": company_filing_status.get(
                    "high_risk_source_mitigation_ready"
                ),
                "high_risk_captcha_unlocker_ready": company_filing_status.get(
                    "high_risk_captcha_unlocker_ready"
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
                "playwright_render_enabled": company_filing_status.get("playwright_render_enabled"),
                "playwright_render_dependency_available": company_filing_status.get(
                    "playwright_render_dependency_available"
                ),
                "playwright_render_browser_available": company_filing_status.get(
                    "playwright_render_browser_available"
                ),
                "playwright_render_runtime": company_filing_status.get("playwright_render_runtime"),
                "playwright_render_configured": company_filing_status.get(
                    "playwright_render_configured"
                ),
                "playwright_render_browser": company_filing_status.get("playwright_render_browser"),
                "playwright_render_wait_until": company_filing_status.get(
                    "playwright_render_wait_until"
                ),
                "playwright_render_timeout_seconds": company_filing_status.get(
                    "playwright_render_timeout_seconds"
                ),
            },
            detail=(
                "這是針對被封鎖、placeholder 或動態文件頁的選配部署強化；"
                "核心抓取仍可透過類瀏覽器 User-Agent 輪替與重試維持可用。"
            ),
        ),
        "company_filing_official_material_information_openapi": _capability(
            "ready"
            if company_filing_status.get("official_material_information_openapi_ready")
            else "degraded",
            evidence=company_filing_status.get(
                "official_material_information_openapi_runtime"
            )
            or {},
            detail=(
                "內建 TWSE/TPEx 官方 OpenAPI 重大訊息 fallback，可取得近期每日重大訊息；"
                "不需要額外付費公司文件 API key。"
            ),
        ),
        "company_filing_structured_api_fallback": _capability(
            "ready"
            if company_filing_status.get("structured_api_configuration_ready")
            else "not_configured",
            evidence={
                "configured": company_filing_status.get("structured_api_configured"),
                "configuration_ready": company_filing_status.get(
                    "structured_api_configuration_ready"
                ),
                "configuration_check": company_filing_status.get(
                    "structured_api_configuration_check"
                ),
                "provider": company_filing_status.get("structured_api_provider"),
                "url_configured": company_filing_status.get("structured_api_url_configured"),
                "token_configured": company_filing_status.get("structured_api_token_configured"),
                "provider_profile_key": structured_api_runtime.get("provider_profile_key"),
                "request_contract": structured_api_runtime.get("request_contract"),
                "retry_policy": structured_api_runtime.get("retry_policy"),
                "response_row_aliases": structured_api_runtime.get("response_row_aliases"),
                "required_document_fields": structured_api_runtime.get(
                    "required_document_fields"
                ),
                "supported_provider_examples": structured_api_runtime.get(
                    "supported_provider_examples"
                ),
                "provider_decision_matrix": structured_api_runtime.get(
                    "provider_decision_matrix"
                ),
                "provider_selection_hint": structured_api_runtime.get(
                    "provider_selection_hint"
                ),
                "provider_setup_preview": structured_api_runtime.get("provider_setup_preview"),
                "local_fixture_api": structured_api_runtime.get("local_fixture_api"),
                "local_fixture_start_cli": structured_api_runtime.get("local_fixture_start_cli"),
                "local_fixture_smoke_cli": structured_api_runtime.get("local_fixture_smoke_cli"),
                "local_fixture_http_smoke_cli": structured_api_runtime.get(
                    "local_fixture_http_smoke_cli"
                ),
                "local_fixture_provider_profile_smoke_cli": structured_api_runtime.get(
                    "local_fixture_provider_profile_smoke_cli"
                ),
                "runtime": structured_api_runtime,
            },
            detail=(
                "選配的付費或專業公司文件來源，適用於法說會簡報、重大訊息與難爬取的 MOPS 揭露。"
            ),
        ),
        "company_filing_structured_api_sample_contract": _capability(
            "ready"
            if structured_api_runtime.get("sample_contract_ready")
            and structured_sample_diagnostics_ready
            else "degraded",
            evidence={
                "ready": structured_api_runtime.get("sample_contract_ready"),
                "contract_diagnostics_ready": structured_sample_diagnostics_ready,
                "smoke_cli": structured_api_runtime.get("sample_contract_cli"),
                "contract": structured_sample_contract,
            },
            detail=(
                "在付費或正式 API 上線前，先用離線樣本資料格式檢查，"
                "確保結構化公司文件 JSON 可轉成 CompanyFilingDocument rows。"
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
    }
