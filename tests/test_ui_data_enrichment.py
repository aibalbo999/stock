from __future__ import annotations

from app.ui.data_enrichment import (
    company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows,
)


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


def test_company_filing_runtime_rows_show_visual_rag_runtime_model() -> None:
    rows = company_filing_runtime_rows(
        {
            "company_filings": {
                "pdf_parser": "auto",
                "pdf_extract_tables": True,
                "pdf_parser_available": True,
                "pdf_table_parser_available": True,
                "pdf_parser_dependencies": {},
                "visual_rag_runtime_available": True,
                "visual_rag_model": "gemini-3.5-flash",
                "visual_rag_runtime_model": "openai/gpt-4o-mini",
                "visual_rag_runtime": {
                    "runtime_model": "openai/gpt-4o-mini",
                    "fallback_reason": None,
                },
            }
        }
    )

    visual_row = next(row for row in rows if row["能力"] == "Visual RAG")
    assert visual_row["狀態"] == "ready"
    assert visual_row["目前"] == "openai/gpt-4o-mini"


def test_company_filing_visual_rag_model_chain_rows_surface_quota_and_rejections() -> None:
    rows = company_filing_visual_rag_model_chain_rows(
        {
            "company_filings": {
                "visual_rag_runtime_model": "gemini-3.5-flash",
                "visual_rag_model_chain": {
                    "quota_hard_routing_enabled": True,
                    "candidate_rows": [
                        {
                            "rank": 1,
                            "model": "gemini-3.5-flash",
                            "model_key": "gemini-3.5-flash",
                            "vision_supported": True,
                            "key_configured": True,
                            "request_budget": 250,
                            "token_budget": None,
                            "routing_tier": "preferred_visual_rag_model",
                        },
                        {
                            "rank": 2,
                            "model": "imagen-4-ultra-generate",
                            "model_key": "imagen-4-ultra-generate",
                            "vision_supported": False,
                            "key_configured": None,
                            "request_budget": None,
                            "token_budget": None,
                            "routing_tier": "fallback",
                        },
                        {
                            "rank": 3,
                            "model": "gemma-4-31b-it",
                            "model_key": "gemma-4-31b-it",
                            "vision_supported": False,
                            "key_configured": None,
                            "request_budget": 14400,
                            "token_budget": None,
                            "routing_tier": "high_quota_text_fallback_excluded_from_vision",
                        },
                    ],
                    "rejected_candidates": [
                        {
                            "rank": 2,
                            "model": "imagen-4-ultra-generate",
                            "model_key": "imagen-4-ultra-generate",
                            "rejection_reason": "non_vision_media_embedding_or_live_model",
                        },
                        {
                            "rank": 3,
                            "model": "gemma-4-31b-it",
                            "model_key": "gemma-4-31b-it",
                            "rejection_reason": "text_only_gemma_fallback",
                        },
                    ],
                }
            }
        }
    )

    assert rows == [
        {
            "順位": 1,
            "模型": "gemini-3.5-flash",
            "Vision": "yes",
            "Runtime": "selected",
            "Key": "ready",
            "每日請求額度": 250,
            "Token 額度": "-",
            "類型": "preferred_visual_rag_model",
            "額度治理": "hard_routing",
            "狀態/排除原因": "vision_candidate",
        },
        {
            "順位": 2,
            "模型": "imagen-4-ultra-generate",
            "Vision": "excluded",
            "Runtime": "-",
            "Key": "-",
            "每日請求額度": "-",
            "Token 額度": "-",
            "類型": "fallback",
            "額度治理": "hard_routing",
            "狀態/排除原因": "non_vision_media_embedding_or_live_model",
        },
        {
            "順位": 3,
            "模型": "gemma-4-31b-it",
            "Vision": "excluded",
            "Runtime": "-",
            "Key": "-",
            "每日請求額度": 14400,
            "Token 額度": "-",
            "類型": "high_quota_text_fallback_excluded_from_vision",
            "額度治理": "hard_routing",
            "狀態/排除原因": "text_only_gemma_fallback",
        },
    ]


def test_company_filing_visual_rag_model_chain_rows_hide_when_missing() -> None:
    assert company_filing_visual_rag_model_chain_rows({}) == []
