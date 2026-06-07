from __future__ import annotations

from app.ui.data_enrichment import company_filing_runtime_rows


def test_company_filing_runtime_rows_surface_pdf_visual_and_external_fallbacks() -> None:
    rows = company_filing_runtime_rows(
        {
            "company_filings": {
                "pdf_parser": "auto",
                "pdf_extract_tables": True,
                "pdf_parser_available": True,
                "pdf_table_parser_available": True,
                "pdf_parser_dependencies": {"fallback_reason": None},
                "visual_rag_runtime_available": False,
                "visual_rag_model": "gemini-3.5-flash",
                "visual_rag_runtime": {"fallback_reason": "missing_vision_llm_key_or_gateway"},
                "playwright_render_configured": True,
                "playwright_render_browser": "chromium",
                "playwright_render_runtime": {"fallback_reason": None, "browser_available": True},
                "browser_render_configured": False,
                "browser_render_provider": "flaresolverr",
                "browser_render_runtime": {"fallback_reason": "browser_render_disabled"},
                "structured_api_configured": False,
                "structured_api_provider": None,
                "structured_api_runtime": {"fallback_reason": "missing_structured_api_provider_or_url"},
            }
        }
    )

    assert rows == [
        {
            "能力": "PDF parser",
            "狀態": "ready",
            "目前": "auto",
            "細節": "-",
            "下一步": "可處理文字型 PDF。",
        },
        {
            "能力": "PDF 表格抽取",
            "狀態": "ready",
            "目前": "enabled",
            "細節": "-",
            "下一步": "可抽取財報表格。",
        },
        {
            "能力": "Visual RAG",
            "狀態": "not_ready",
            "目前": "gemini-3.5-flash",
            "細節": "missing_vision_llm_key_or_gateway",
            "下一步": "檢查 PyMuPDF、COMPANY_FILING_VISUAL_RAG_MODEL 與 vision LLM key/gateway。",
        },
        {
            "能力": "Playwright render",
            "狀態": "ready",
            "目前": "chromium",
            "細節": "-",
            "下一步": "可處理動態 IR/公開文件頁。",
        },
        {
            "能力": "Browser / unlocker",
            "狀態": "not_ready",
            "目前": "flaresolverr",
            "細節": "browser_render_disabled",
            "下一步": "設定 Browserless、FlareSolverr、ScrapingBee 或 BrightData render URL。",
        },
        {
            "能力": "結構化文件 API",
            "狀態": "optional",
            "目前": "-",
            "細節": "missing_structured_api_provider_or_url",
            "下一步": "若 MOPS/IR 常被擋，可串接 TEJ 或專業文件 API。",
        },
    ]


def test_company_filing_runtime_rows_hide_when_service_status_missing() -> None:
    assert company_filing_runtime_rows({}) == []
