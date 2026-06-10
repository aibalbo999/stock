from __future__ import annotations

from datetime import date

from app.ui.data_enrichment import (
    company_filing_runtime_rows,
    company_filing_visual_rag_model_chain_rows,
)
from app.ui import data_enrichment_market
from app.ui.data_enrichment_market import market_data_operation_button_type
from app.ui.data_enrichment_market import market_cache_operator_summary


def test_company_filing_runtime_rows_surface_pdf_visual_and_external_fallbacks() -> None:
    rows = company_filing_runtime_rows(
        {
            "company_filings": {
                "pdf_parser": "auto",
                "pdf_extract_tables": True,
                "pdf_parser_available": True,
                "pdf_table_parser_available": True,
                "pdf_table_quality_provenance_enabled": True,
                "pdf_table_quality_provenance_prefix": "[PDF 表格品質]",
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
                "official_material_information_openapi_ready": True,
                "official_material_information_openapi_provider": "twse_tpex_official_openapi",
                "official_material_information_openapi_runtime": {"ready": True},
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
            "細節": "quality=[PDF 表格品質]",
            "下一步": "可抽取財報表格，並標記表格品質風險。",
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
            "能力": "重大訊息 OpenAPI",
            "狀態": "ready",
            "目前": "twse_tpex_official_openapi",
            "細節": "-",
            "下一步": "可補近期官方重大訊息。",
        },
        {
            "能力": "結構化文件 API",
            "狀態": "optional",
            "目前": "-",
            "細節": "missing_structured_api_provider_or_url",
            "下一步": "若 MOPS/IR 常被擋，可串接 TEJ 或專業文件 API。",
        },
    ]


def test_market_data_operation_button_type_prioritizes_pending_operation() -> None:
    assert market_data_operation_button_type(None, "market_refresh") == "primary"
    assert market_data_operation_button_type(None, "valuation_refresh") == "secondary"
    assert (
        market_data_operation_button_type("company_filings_fetch", "company_filings_fetch")
        == "primary"
    )
    assert market_data_operation_button_type("company_filings_fetch", "market_refresh") == (
        "secondary"
    )
    assert market_data_operation_button_type("valuation_refresh", "valuation_refresh") == (
        "primary"
    )


def test_market_operation_readiness_rows_show_pending_operation_and_ready_state() -> None:
    assert hasattr(data_enrichment_market, "market_operation_readiness_rows")
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330", "2382"],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation="valuation_refresh",
    )

    assert [row["operation"] for row in rows] == [
        "market_refresh",
        "fundamentals_refresh",
        "valuation_refresh",
        "company_filings_fetch",
    ]
    assert rows[0] == {
        "operation": "market_refresh",
        "label": "刷新股價",
        "state": "ready",
        "selected": "no",
        "caption": "2 檔｜2026-06-01 → 2026-06-10",
        "disabled_reason": "可送出背景任務",
        "impact": "更新最新版報告的股價與成交量判讀。",
        "post_action_hint": "完成後回報告中心確認是否需要重跑。",
        "button_type": "secondary",
    }
    assert rows[2]["operation"] == "valuation_refresh"
    assert rows[2]["selected"] == "yes"
    assert rows[2]["button_type"] == "primary"
    assert rows[2]["disabled_reason"] == "可送出背景任務"


def test_market_operation_readiness_rows_explain_missing_tickers() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=[],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation=None,
    )

    assert {row["state"] for row in rows} == {"attention"}
    assert {row["disabled_reason"] for row in rows} == {"請先選擇至少一檔股票"}
    assert rows[0]["button_type"] == "primary"
    assert rows[1]["button_type"] == "secondary"


def test_market_operation_readiness_rows_explain_invalid_date_range_only_where_needed() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 10),
        market_end=date(2026, 6, 1),
        pending_operation="market_refresh",
    )

    by_operation = {row["operation"]: row for row in rows}
    assert by_operation["market_refresh"]["state"] == "attention"
    assert by_operation["market_refresh"]["disabled_reason"] == "起始日期不可晚於結束日期"
    assert by_operation["valuation_refresh"]["state"] == "attention"
    assert by_operation["valuation_refresh"]["disabled_reason"] == "起始日期不可晚於結束日期"
    assert by_operation["fundamentals_refresh"]["state"] == "ready"
    assert by_operation["fundamentals_refresh"]["disabled_reason"] == "可送出背景任務"
    assert by_operation["company_filings_fetch"]["state"] == "ready"
    assert by_operation["company_filings_fetch"]["disabled_reason"] == "可送出背景任務"


def test_market_operation_readiness_rows_block_when_worker_offline() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation="market_refresh",
        task_queue={"ready": True, "processing_ready": False, "worker_online": False},
    )

    assert {row["state"] for row in rows} == {"blocked"}
    assert {row["disabled_reason"] for row in rows} == {
        "背景任務未就緒，請先到維護頁檢查 Worker"
    }
    assert rows[0]["selected"] == "yes"
    assert rows[0]["button_type"] == "primary"


def test_market_operation_readiness_rows_show_queue_status_when_unavailable() -> None:
    rows = data_enrichment_market.market_operation_readiness_rows(
        selected_market_tickers=["2330"],
        market_start=date(2026, 6, 1),
        market_end=date(2026, 6, 10),
        pending_operation=None,
        task_queue={"ready": False, "worker_online": True},
    )

    assert {row["state"] for row in rows} == {"blocked"}
    assert {row["disabled_reason"] for row in rows} == {
        "背景任務未就緒，請先到維護頁檢查 Redis/Celery"
    }


def test_market_cache_operator_summary_flags_stale_and_missing_cache() -> None:
    rows = market_cache_operator_summary(
        {
            "tickers": ["2330", "2382"],
            "market_snapshots": [
                {
                    "ticker": "2330",
                    "trade_date": "2026-06-05",
                    "source": "FinMind TaiwanStockPrice; cached-stale",
                }
            ],
            "valuations": [
                {"ticker": "2330", "trade_date": "2026-06-04", "source": "FinMind"},
                {"ticker": "2382", "trade_date": "2026-06-04", "source": "FinMind"},
            ],
            "company_filings": [],
            "financial_metric_count": 0,
        }
    )

    assert rows == [
        {
            "title": "股價快取",
            "value": "1 / 2 檔",
            "state": "attention",
            "caption": "含快取救援資料，缺 1 檔；建議刷新股價。",
            "action_label": "刷新股價",
        },
        {
            "title": "估值快取",
            "value": "2 / 2 檔",
            "state": "ready",
            "caption": "最新交易日 2026-06-04。",
            "action_label": "可沿用",
        },
        {
            "title": "財報快取",
            "value": "0 筆",
            "state": "attention",
            "caption": "尚無財報三表科目快取；建議刷新 5 年財報。",
            "action_label": "刷新 5 年財報",
        },
        {
            "title": "公司文件",
            "value": "0 筆",
            "state": "attention",
            "caption": "尚無公司文件快取；若報告缺法說或公開資訊，請補抓公司文件。",
            "action_label": "補抓公司文件",
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
