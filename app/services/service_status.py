from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from urllib.parse import urlparse

import redis

from app.core.config import get_settings
from app.data_sources.company_filings import (
    COMPANY_FILING_RETRYABLE_HTTP_STATUSES,
    DEFAULT_COMPANY_FILING_USER_AGENTS,
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
)
from app.data_sources.market import FUGLE_RETRYABLE_HTTP_STATUSES, FINMIND_RETRYABLE_HTTP_STATUSES, MarketDataClient
from app.db.migration_status import db_migration_status
from app.db.session import engine
from app.rag.vector_store import VectorStore
from app.rag.reranker import RagReranker
from app.services.candidate_confidence import confidence_thresholds
from app.services.company_filing_cache import RedisCompanyFilingCache
from app.services.llm_client import RETRYABLE_HTTP_STATUSES
from app.services.source_quality import SOURCE_CREDIBILITY_LABELS, SOURCE_CREDIBILITY_WEIGHTS
from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.whitelist import SupplyChainWhitelist
from app.services.workflow_orchestration import workflow_orchestration_status


def service_status() -> dict:
    settings = get_settings()
    high_threshold, medium_threshold = confidence_thresholds()
    embedding_status = VectorStore.runtime_embedding_provider_status(settings)
    retrieval_status = VectorStore.retrieval_runtime_status(settings)
    chroma_available = _module_available("chromadb")
    reranker = RagReranker()
    reranker_status = reranker.status()
    redis_status = _redis_status(settings.redis_url)
    company_filing_user_agent_status = _company_filing_user_agent_status(
        settings.company_filing_user_agents
    )
    company_filing_proxy_count = len(_split_config_values(settings.company_filing_proxy_urls))
    company_filing_pdf_parser_status = _company_filing_pdf_parser_status(
        settings.company_filing_pdf_parser,
        extract_tables=settings.company_filing_pdf_extract_tables,
    )
    company_filing_user_agent_count = int(
        company_filing_user_agent_status.get("effective_user_agent_count") or 0
    )
    company_filing_browser_render_runtime = company_filing_browser_render_status()
    company_filing_browser_render_configured = bool(
        company_filing_browser_render_runtime.get("runtime_available")
    )
    company_filing_playwright_runtime = company_filing_playwright_browser_status(
        settings.company_filing_playwright_browser
    )
    company_filing_playwright_dependency_available = bool(
        company_filing_playwright_runtime.get("dependency_available")
    )
    company_filing_playwright_browser_available = bool(
        company_filing_playwright_runtime.get("browser_available")
    )
    company_filing_playwright_configured = bool(
        settings.company_filing_playwright_render_enabled
        and company_filing_playwright_browser_available
    )
    llm_fallback_models = _llm_effective_fallback_models(settings)
    llm_local_gateway_configured = any(
        _llm_model_provider(model) == "local" for model in llm_fallback_models
    )
    status = {
        "database": {
            "init_mode": settings.database_init_mode,
            "create_all_non_sqlite_allowed": settings.database_allow_create_all_non_sqlite,
            "migration": db_migration_status(bind=engine),
        },
        "redis": redis_status,
        "gemini": {
            "configured": len(settings.gemini_api_keys) > 0,
            "key_count": len(settings.gemini_api_keys),
            "model": settings.primary_llm_model,
            "provider": settings.llm_provider,
            "fallback_models": llm_fallback_models,
            "provider_keys_configured": {
                "gemini": len(settings.gemini_api_keys) > 0,
                "openai": bool(settings.openai_api_key),
                "anthropic": bool(settings.anthropic_api_key),
                "local": llm_local_gateway_configured,
            },
            "retryable_http_statuses": sorted(RETRYABLE_HTTP_STATUSES),
            "max_retries_per_key": max(0, int(settings.llm_max_retries_per_key)),
            "base_retry_delay_seconds": max(0.0, float(settings.llm_base_retry_delay_seconds)),
            "max_retry_delay_seconds": max(0.0, float(settings.llm_max_retry_delay_seconds)),
        },
        "finmind": {
            "configured": bool(settings.finmind_token),
            "public_fallback_enabled": settings.finmind_public_fallback_enabled,
            "data_access_ready": bool(settings.finmind_token or settings.finmind_public_fallback_enabled),
            "mode": (
                "authenticated"
                if settings.finmind_token
                else "public_limited"
                if settings.finmind_public_fallback_enabled
                else "disabled"
            ),
            "retryable_http_statuses": sorted(FINMIND_RETRYABLE_HTTP_STATUSES),
            "max_retries": max(0, int(settings.finmind_max_retries)),
            "base_retry_delay_seconds": max(0.0, float(settings.finmind_base_retry_delay_seconds)),
            "max_retry_delay_seconds": max(0.0, float(settings.finmind_max_retry_delay_seconds)),
            "timeout_seconds": max(1.0, float(settings.finmind_timeout_seconds)),
            "connect_timeout_seconds": max(1.0, float(settings.finmind_connect_timeout_seconds)),
            "concurrency": max(1, int(settings.finmind_concurrency)),
            "circuit_breaker_enabled": bool(settings.finmind_circuit_breaker_enabled),
            "circuit_breaker_failure_threshold": max(
                1,
                int(settings.finmind_circuit_breaker_failure_threshold),
            ),
            "circuit_breaker_recovery_seconds": max(
                0.0,
                float(settings.finmind_circuit_breaker_recovery_seconds),
            ),
        },
        "fugle": {
            "configured": bool(settings.fugle_api_key),
            "price_history_provider": True,
            "price_fallback_endpoints": ["historical/candles", "historical/stats"],
            "provider_order": _split_config_values(settings.market_price_provider_order),
            "retryable_http_statuses": sorted(FUGLE_RETRYABLE_HTTP_STATUSES),
            "max_retries": max(0, int(settings.fugle_max_retries)),
            "base_retry_delay_seconds": max(0.0, float(settings.fugle_base_retry_delay_seconds)),
            "max_retry_delay_seconds": max(0.0, float(settings.fugle_max_retry_delay_seconds)),
            "timeout_seconds": max(1.0, float(settings.fugle_timeout_seconds)),
            "connect_timeout_seconds": max(1.0, float(settings.fugle_connect_timeout_seconds)),
            "circuit_breaker_enabled": bool(settings.fugle_circuit_breaker_enabled),
            "circuit_breaker_failure_threshold": max(
                1,
                int(settings.fugle_circuit_breaker_failure_threshold),
            ),
            "circuit_breaker_recovery_seconds": max(
                0.0,
                float(settings.fugle_circuit_breaker_recovery_seconds),
            ),
        },
        "market_data_cache": {
            "enabled": settings.market_data_cache_enabled,
            "available": bool(settings.market_data_cache_enabled and redis_status.get("ok")),
            "backend": "redis",
            "stale_rescue_enabled": True,
            "stale_source_marker": MarketDataClient.STALE_CACHE_SOURCE_MARKER,
            "latest_only_source_marker": MarketDataClient.LATEST_ONLY_SOURCE_MARKER,
            "price_provider_order": _split_config_values(settings.market_price_provider_order),
            "provider_matrix": _market_data_provider_matrix(settings),
            "datasets": [
                "TaiwanStockPrice",
                "TaiwanStockMonthRevenue",
                "TaiwanStockFinancialStatements",
                "TaiwanStockBalanceSheet",
                "TaiwanStockCashFlowsStatement",
                "TaiwanStockPER",
            ],
            "price_history_ttl_seconds": settings.price_history_cache_ttl_seconds,
            "monthly_revenue_ttl_seconds": settings.monthly_revenue_cache_ttl_seconds,
            "financial_metrics_ttl_seconds": settings.financial_metrics_cache_ttl_seconds,
            "valuation_metrics_ttl_seconds": settings.valuation_metrics_cache_ttl_seconds,
            "official_openapi_fallback_enabled": settings.market_official_openapi_fallback_enabled,
            "official_openapi_timeout_seconds": settings.market_official_openapi_timeout_seconds,
        },
        "company_filings": {
            **company_filing_user_agent_status,
            "proxy_count": company_filing_proxy_count,
            "user_agent_retry_rotation_enabled": company_filing_user_agent_count > 1,
            "proxy_retry_rotation_enabled": company_filing_proxy_count > 1,
            "identity_retry_rotation_enabled": (
                company_filing_user_agent_count > 1 or company_filing_proxy_count > 1
            ),
            "http_retries": max(0, int(settings.company_filing_http_retries)),
            "retryable_http_statuses": sorted(COMPANY_FILING_RETRYABLE_HTTP_STATUSES),
            "base_retry_delay_seconds": max(0.0, float(settings.company_filing_base_retry_delay_seconds)),
            "max_retry_delay_seconds": max(0.0, float(settings.company_filing_max_retry_delay_seconds)),
            "pdf_parser": settings.company_filing_pdf_parser,
            "pdf_extract_tables": settings.company_filing_pdf_extract_tables,
            "pdf_parser_dependencies": company_filing_pdf_parser_status,
            "pdf_parser_available": company_filing_pdf_parser_status.get("configured_parser_available"),
            "pdf_table_parser_available": company_filing_pdf_parser_status.get("table_parser_available"),
            "pdf_table_extraction_runtime_available": company_filing_pdf_parser_status.get(
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
            "browser_render_url_configured": company_filing_browser_render_runtime.get("url_configured"),
            "browser_render_endpoint_reachable": company_filing_browser_render_runtime.get(
                "endpoint_reachable"
            ),
            "browser_render_runtime": company_filing_browser_render_runtime,
            "browser_render_configured": company_filing_browser_render_configured,
            "browser_render_concurrency": max(
                1,
                int(settings.company_filing_browser_render_concurrency),
            ),
            "playwright_render_enabled": settings.company_filing_playwright_render_enabled,
            "playwright_render_dependency_available": company_filing_playwright_dependency_available,
            "playwright_render_browser_available": company_filing_playwright_browser_available,
            "playwright_render_runtime": company_filing_playwright_runtime,
            "playwright_render_configured": company_filing_playwright_configured,
            "playwright_render_browser": settings.company_filing_playwright_browser,
            "playwright_render_wait_until": settings.company_filing_playwright_wait_until,
            "playwright_render_timeout_seconds": settings.company_filing_playwright_timeout_seconds,
            "browser_or_proxy_fallback_configured": bool(
                company_filing_browser_render_configured
                or company_filing_playwright_configured
                or _split_config_values(settings.company_filing_proxy_urls)
            ),
            "browser_render_timeout_seconds": settings.company_filing_browser_render_timeout_seconds,
        },
        "vector_store": {
            "use_chroma": settings.use_chroma,
            "chroma_available": chroma_available,
            "path": str(settings.vector_db_path),
            "storage_mode": "http" if settings.chroma_api_url else "persistent",
            "chroma_api_url_configured": bool(settings.chroma_api_url),
            "chroma_api_url": _redact_url(settings.chroma_api_url),
            "chroma_tenant": settings.chroma_tenant,
            "chroma_database": settings.chroma_database,
            "embedding_provider": settings.rag_embedding_provider,
            "embedding_model": settings.rag_embedding_model,
            "allow_chroma_default_embedding_fallback": settings.rag_allow_chroma_default_embedding_fallback,
            "persistent_collection_enabled": _vector_store_persistent_collection_enabled(
                settings,
                embedding_status,
                chroma_available,
            ),
            "embedding_status": embedding_status,
            "retrieval_status": retrieval_status,
            "hybrid_search_enabled": settings.rag_hybrid_search_enabled,
            "vector_weight": settings.rag_vector_weight,
            "keyword_weight": settings.rag_keyword_weight,
            "rerank_top_k": settings.rag_rerank_top_k,
            "keyword_corpus_limit": settings.rag_keyword_corpus_limit,
            "reranker_provider": settings.rag_reranker_provider,
            "reranker_model": settings.rag_reranker_model,
            "reranker_text_limit": settings.rag_reranker_text_limit,
            "reranker_available": reranker_status["available"],
            "reranker_status": reranker_status,
        },
        "supply_chain_graph": _supply_chain_graph_status(),
        "celery": {
            "broker_url": _redact_url(settings.redis_url),
            "backend_url": _redact_url(settings.redis_url),
        },
        "workflow_orchestration": workflow_orchestration_status(settings),
        "candidate_confidence": {
            "high_threshold": high_threshold,
            "medium_threshold": medium_threshold,
            "promotion_rule": "正式分析需至少 2 篇證據、2 個來源，證據信心達高信心門檻，且低可信來源不得單獨支撐高信心。",
            "source_credibility_weights": SOURCE_CREDIBILITY_WEIGHTS,
            "source_credibility_labels": SOURCE_CREDIBILITY_LABELS,
        },
    }
    status["upgrade_capability_matrix"] = _upgrade_capability_matrix(status)
    return status


def _upgrade_capability_matrix(status: dict) -> dict:
    vector_store = status.get("vector_store") or {}
    embedding_status = vector_store.get("embedding_status") or {}
    retrieval_status = vector_store.get("retrieval_status") or {}
    reranker_status = vector_store.get("reranker_status") or {}
    llm_status = status.get("gemini") or {}
    graph_status = status.get("supply_chain_graph") or {}
    workflow_status = status.get("workflow_orchestration") or {}
    database_status = status.get("database") or {}
    migration_status = database_status.get("migration") or {}
    market_cache_status = status.get("market_data_cache") or {}
    company_filing_status = status.get("company_filings") or {}
    api_status = _api_controller_status()
    market_provider_readiness = _market_data_provider_readiness(
        market_cache_status,
        status.get("finmind") or {},
        status.get("fugle") or {},
    )

    llm_provider = str(llm_status.get("provider") or "")
    llm_dependency = "litellm" if llm_provider == "litellm" else "google.genai"
    llm_uses_sdk = llm_provider in {"litellm", "google_genai"}
    llm_dependency_available = _module_available(llm_dependency) if llm_uses_sdk else False
    llm_keys = llm_status.get("provider_keys_configured") or {}
    llm_fallback_models = llm_status.get("fallback_models") or []
    llm_fallback_readiness = _llm_fallback_readiness(llm_fallback_models, llm_keys)
    if llm_provider == "litellm":
        provider_key_ready = any(bool(value) for value in llm_keys.values())
    elif llm_provider == "google_genai":
        provider_key_ready = bool(llm_keys.get("gemini"))
    else:
        provider_key_ready = False
    llm_sdk_ready = bool(llm_uses_sdk and llm_dependency_available and provider_key_ready)
    llm_fallback_ready = any(item.get("key_configured") for item in llm_fallback_readiness)

    return {
        "ai_rag": {
            "multilingual_embedding": _capability(
                "ready"
                if embedding_status.get("custom_embedding_enabled")
                else "degraded",
                evidence={
                    "provider": embedding_status.get("provider"),
                    "model": embedding_status.get("model"),
                    "custom_embedding_requested": embedding_status.get("custom_embedding_requested"),
                    "custom_embedding_enabled": embedding_status.get("custom_embedding_enabled"),
                    "fallback_reason": embedding_status.get("fallback_reason"),
                },
                detail="Chroma uses an explicit multilingual/provider embedding function when enabled.",
            ),
            "llm_sdk_and_fallback": _capability(
                "ready"
                if llm_sdk_ready and llm_fallback_ready
                else "degraded",
                evidence={
                    "provider": llm_provider,
                    "dependency": llm_dependency if llm_uses_sdk else None,
                    "dependency_available": llm_dependency_available,
                    "sdk_ready": llm_sdk_ready,
                    "fallback_models": llm_fallback_models,
                    "fallback_model_count": len(llm_fallback_models),
                    "fallback_model_ready_count": sum(
                        1 for item in llm_fallback_readiness if item.get("key_configured")
                    ),
                    "fallback_model_readiness": llm_fallback_readiness,
                    "provider_keys_configured": llm_keys,
                },
                detail=(
                    "LiteLLM / Google GenAI SDK path is selected; status is ready only when at least one "
                    "configured fallback model has a matching provider key; only explicit local/ollama/lm_studio "
                    "models are treated as no-key local gateways."
                ),
            ),
            "hybrid_search": _capability(
                "ready"
                if retrieval_status.get("hybrid_search_enabled") and retrieval_status.get("bm25_enabled")
                else "degraded",
                evidence={
                    "strategy": retrieval_status.get("strategy"),
                    "bm25_enabled": retrieval_status.get("bm25_enabled"),
                    "tokenizer": retrieval_status.get("tokenizer"),
                    "vector_weight": retrieval_status.get("vector_weight"),
                    "keyword_weight": retrieval_status.get("keyword_weight"),
                    "retrieval_trace_enabled": retrieval_status.get("retrieval_trace_enabled"),
                    "retrieval_trace_fields": retrieval_status.get("retrieval_trace_fields"),
                },
            ),
            "reranking": _capability(
                "ready" if reranker_status.get("model_reranker_ready") else "degraded",
                evidence={
                    "provider": reranker_status.get("provider"),
                    "configured_provider": reranker_status.get("configured_provider"),
                    "resolved_provider": reranker_status.get("resolved_provider"),
                    "execution_mode": reranker_status.get("execution_mode"),
                    "available": reranker_status.get("available"),
                    "quality_tier": reranker_status.get("quality_tier"),
                    "is_model_reranker": reranker_status.get("is_model_reranker"),
                    "model_reranker_ready": reranker_status.get("model_reranker_ready"),
                    "keyword_fallback": reranker_status.get("keyword_fallback"),
                    "dependency_available": reranker_status.get("dependency_available"),
                    "api_key_configured": reranker_status.get("api_key_configured"),
                    "model_available": reranker_status.get("model_available"),
                    "model_reranker_gap": reranker_status.get("model_reranker_gap"),
                    "auto_candidates": reranker_status.get("auto_candidates"),
                    "fallback_reason": reranker_status.get("fallback_reason"),
                },
                detail=(
                    "Ready only when a learned/API reranker is configured and available; "
                    "keyword mode remains an operational fallback but is not counted as model reranking."
                ),
            ),
            "graphrag_context": _capability(
                "ready"
                if graph_status.get("enabled") and graph_status.get("query_expansion_enabled")
                else "degraded",
                evidence={
                    "node_count": graph_status.get("node_count"),
                    "edge_count": graph_status.get("edge_count"),
                    "edge_confidence": graph_status.get("edge_confidence"),
                    "retrieval_query_plan_enabled": graph_status.get("retrieval_query_plan_enabled"),
                    "retrieval_query_strategy": graph_status.get("retrieval_query_strategy"),
                    "retrieval_evidence_policy": graph_status.get("retrieval_evidence_policy"),
                    "retrieval_query_example": graph_status.get("retrieval_query_example"),
                    "neo4j_export_enabled": graph_status.get("neo4j_export_enabled"),
                },
                detail=graph_status.get("purpose"),
            ),
            "neo4j_payload_export": _capability(
                "ready"
                if (graph_status.get("neo4j_import") or {}).get("payload_export_ready")
                else "degraded",
                evidence={
                    "payload_export_ready": (graph_status.get("neo4j_import") or {}).get(
                        "payload_export_ready"
                    ),
                    "payload_format": (graph_status.get("neo4j_import") or {}).get("payload_format"),
                    "payload_node_count": (graph_status.get("neo4j_import") or {}).get(
                        "payload_node_count"
                    ),
                    "payload_structural_edge_count": (graph_status.get("neo4j_import") or {}).get(
                        "payload_structural_edge_count"
                    ),
                    "payload_peer_edge_count": (graph_status.get("neo4j_import") or {}).get(
                        "payload_peer_edge_count"
                    ),
                    "payload_statement_count": (graph_status.get("neo4j_import") or {}).get(
                        "payload_statement_count"
                    ),
                    "payload_export_endpoint": (graph_status.get("neo4j_import") or {}).get(
                        "payload_export_endpoint"
                    ),
                    "payload_dry_run_cli": (graph_status.get("neo4j_import") or {}).get(
                        "payload_dry_run_cli"
                    ),
                },
                detail="Ready means GraphRAG can produce parameterized Neo4j Cypher payloads without requiring a live Neo4j connection.",
            ),
            "neo4j_import": _capability(
                _neo4j_import_capability_status(graph_status.get("neo4j_import") or {}),
                evidence=graph_status.get("neo4j_import") or {},
                detail="External Neo4j import is ready only when URI, dependency, auth, and connection checks are available.",
            ),
        },
        "architecture": {
            "thin_api_controller": _capability(
                "ready"
                if (api_status.get("main_py_lines") or 10_000) <= 600
                and api_status["route_module_count"] >= 7
                else "degraded",
                evidence=api_status,
                detail="FastAPI endpoints are split into router modules and use-case services.",
            ),
            "workflow_orchestration": _capability(
                "ready" if workflow_status.get("ready") else "degraded",
                evidence={
                    "engine": workflow_status.get("engine"),
                    "mode": workflow_status.get("mode"),
                    "checkpoint_store": workflow_status.get("checkpoint_store"),
                    "local_fallback_enabled": workflow_status.get("local_fallback_enabled"),
                    "fallback_reason": workflow_status.get("fallback_reason"),
                },
            ),
            "database_migrations": _capability(
                "ready"
                if migration_status.get("ok")
                and migration_status.get("head_revision")
                and migration_status.get("up_to_date")
                else "degraded",
                evidence={
                    "init_mode": database_status.get("init_mode"),
                    "head_revision": migration_status.get("head_revision"),
                    "current_revision": migration_status.get("current_revision"),
                    "up_to_date": migration_status.get("up_to_date"),
                    "version_table_present": migration_status.get("version_table_present"),
                },
                detail="Alembic is present; current DB may still need upgrade/stamp when up_to_date=false.",
            ),
        },
        "data_business_logic": {
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
                    "fugle_configured": (status.get("fugle") or {}).get("configured"),
                    "finmind_configured": (status.get("finmind") or {}).get("configured"),
                    **market_provider_readiness,
                },
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
                    "effective_user_agent_count": company_filing_status.get("effective_user_agent_count"),
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
                    "http_retries": company_filing_status.get("http_retries"),
                    "retryable_http_statuses": company_filing_status.get("retryable_http_statuses"),
                    "pdf_parser": company_filing_status.get("pdf_parser"),
                    "pdf_extract_tables": company_filing_status.get("pdf_extract_tables"),
                    "pdf_parser_available": company_filing_status.get("pdf_parser_available"),
                    "pdf_parser_dependencies": company_filing_status.get("pdf_parser_dependencies"),
                    "html_extract_tables": company_filing_status.get("html_extract_tables"),
                    "browser_render_configured": company_filing_status.get("browser_render_configured"),
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
                    "pdf_table_parser_available": company_filing_status.get("pdf_table_parser_available"),
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
                    "browser_render_configured": company_filing_status.get("browser_render_configured"),
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
                    "playwright_render_runtime": company_filing_status.get(
                        "playwright_render_runtime"
                    ),
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
                    "Optional deployment hardening for blocked, placeholder, or dynamic filing pages. "
                    "Core fetch remains usable through browser-like User-Agent rotation and retries."
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
                if (status.get("candidate_confidence") or {})
                .get("source_credibility_weights", {})
                .get("investment_blog", 1.0)
                < 0.75
                else "degraded",
                evidence={
                    "promotion_rule": (status.get("candidate_confidence") or {}).get("promotion_rule"),
                    "source_credibility_weights": (status.get("candidate_confidence") or {}).get(
                        "source_credibility_weights"
                    ),
                },
            ),
        },
    }


def _capability(state: str, *, evidence: dict, detail: str | None = None) -> dict:
    payload = {
        "status": state,
        "evidence": evidence,
    }
    if detail:
        payload["detail"] = detail
    return payload


def _api_controller_status() -> dict:
    api_dir = Path(__file__).resolve().parents[1] / "api"
    main_path = api_dir / "main.py"
    try:
        main_py_lines = len(main_path.read_text(encoding="utf-8").splitlines())
    except OSError:
        main_py_lines = None
    route_modules = sorted(path.name for path in api_dir.glob("*_routes.py"))
    return {
        "main_py_lines": main_py_lines,
        "route_module_count": len(route_modules),
        "route_modules": route_modules,
        "service_factory_present": (api_dir / "service_factory.py").exists(),
        "legacy_facade_present": (api_dir / "legacy_facade.py").exists(),
    }


def _supply_chain_graph_status() -> dict:
    try:
        graph = SupplyChainWhitelist().graph()
        neo4j_payload = graph.neo4j_import_payload()
        sample_ticker = graph.nodes[0].ticker if graph.nodes else ""
        retrieval_plan = graph.retrieval_plan([sample_ticker], topic="AI 產業鏈") if sample_ticker else {}
        neo4j_import = {
            **Neo4jGraphImportService().status(),
            "payload_export_ready": bool(
                neo4j_payload.get("format") == "neo4j_cypher_v1"
                and neo4j_payload.get("statements")
                and neo4j_payload.get("parameters", {}).get("nodes")
            ),
            "payload_format": neo4j_payload.get("format"),
            "payload_node_count": len(neo4j_payload.get("parameters", {}).get("nodes") or []),
            "payload_structural_edge_count": len(
                neo4j_payload.get("parameters", {}).get("structural_edges") or []
            ),
            "payload_peer_edge_count": len(neo4j_payload.get("parameters", {}).get("peer_edges") or []),
            "payload_statement_count": len(neo4j_payload.get("statements") or []),
            "payload_export_endpoint": "GET /supply-chain/graph/neo4j",
            "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
        }
        return {
            "enabled": True,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "edge_confidence": "taxonomy",
            "query_expansion_enabled": True,
            "retrieval_hints_enabled": True,
            "retrieval_query_plan_enabled": bool(retrieval_plan.get("queries_by_ticker")),
            "retrieval_query_strategy": retrieval_plan.get("strategy"),
            "retrieval_evidence_policy": retrieval_plan.get("evidence_policy"),
            "retrieval_query_example": next(
                iter((retrieval_plan.get("queries_by_ticker") or {}).values()),
                [],
            )[:2],
            "prompt_context_enabled": True,
            "neo4j_export_enabled": True,
            "neo4j_import": neo4j_import,
            "purpose": "GraphRAG context for structural upstream/downstream retrieval, not direct supplier proof.",
        }
    except Exception as exc:
        return {"enabled": False, "error": str(exc)}


def _neo4j_import_capability_status(status: dict) -> str:
    if status.get("ready"):
        return "ready"
    if status.get("payload_export_ready"):
        return "degraded"
    if not status.get("configured"):
        return "not_configured"
    return "degraded"


def _llm_fallback_readiness(fallback_models: list[str], provider_keys: dict) -> list[dict]:
    rows = []
    for model in fallback_models:
        provider = _llm_model_provider(model)
        key_configured = bool(provider_keys.get(provider)) if provider in provider_keys else None
        rows.append(
            {
                "model": model,
                "provider": provider,
                "key_configured": key_configured,
            }
        )
    return rows


def _llm_model_provider(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if normalized.startswith(("gemini", "gemma")) or normalized.startswith("google/"):
        return "gemini"
    if normalized.startswith("anthropic/") or normalized.startswith("claude"):
        return "anthropic"
    if normalized.startswith("openai/") or normalized.startswith("gpt-"):
        return "openai"
    if normalized.startswith(("ollama/", "lm_studio/", "local/")):
        return "local"
    return "unknown"


def _llm_effective_fallback_models(settings) -> list[str]:
    models = [
        model.strip()
        for model in str(settings.llm_fallback_models or "").split(",")
        if model.strip()
    ]
    provider = str(getattr(settings, "llm_provider", "") or "").lower().replace("-", "_")
    local_model = str(getattr(settings, "local_llm_model", "") or "").strip()
    if provider == "litellm" and local_model:
        models.append(local_model)
    primary = str(getattr(settings, "primary_llm_model", "") or "").strip()
    return list(dict.fromkeys(model for model in models if model and model != primary))


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


def _company_filing_pdf_parser_status(parser: str, *, extract_tables: bool) -> dict:
    normalized_parser = str(parser or "auto").strip().lower() or "auto"
    pdfplumber_available = _module_available("pdfplumber")
    unstructured_pdf_available = _module_available("unstructured.partition.pdf")
    pypdf_available = _module_available("pypdf")
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


def _vector_store_persistent_collection_enabled(
    settings,
    embedding_status: dict,
    chroma_available: bool,
) -> bool:
    if not settings.use_chroma:
        return False
    if not chroma_available:
        return False
    if not embedding_status.get("custom_embedding_requested"):
        return True
    if embedding_status.get("custom_embedding_enabled"):
        return True
    return bool(settings.rag_allow_chroma_default_embedding_fallback)


def _redis_status(redis_url: str) -> dict:
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        pong = client.ping()
        return {"ok": bool(pong), "url": _redact_url(redis_url)}
    except Exception as exc:
        return {"ok": False, "url": _redact_url(redis_url), "error": str(exc)}


def _split_config_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _market_data_provider_matrix(settings) -> dict:
    price_provider_order = _split_config_values(settings.market_price_provider_order)
    finmind_configured = bool(settings.finmind_token)
    finmind_public_fallback_enabled = bool(settings.finmind_public_fallback_enabled)
    finmind_ready = bool(finmind_configured or finmind_public_fallback_enabled)
    finmind_provider_label = "finmind_authenticated" if finmind_configured else "finmind_public_limited"
    fugle_configured = bool(settings.fugle_api_key)
    official_openapi_enabled = bool(settings.market_official_openapi_fallback_enabled)
    official_provider = "twse_tpex_openapi_latest"
    price_live_providers = list(price_provider_order or ["finmind"])
    if official_openapi_enabled and official_provider not in price_live_providers:
        price_live_providers.append(official_provider)
    return {
        "price_history": {
            "label": "股價歷史",
            "live_providers": price_live_providers,
            "fallback_enabled": "fugle" in price_provider_order,
            "fallback_configured": bool("fugle" in price_provider_order and fugle_configured),
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready and "finmind" in price_live_providers),
                    ("fugle", fugle_configured and "fugle" in price_live_providers),
                    (official_provider, official_openapi_enabled and official_provider in price_live_providers),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fugle_fallback_endpoints": ["historical/candles", "historical/stats"],
            "official_openapi_latest_snapshot_fallback": official_openapi_enabled,
            "redis_cache_ttl_seconds": settings.price_history_cache_ttl_seconds,
        },
        "monthly_revenue": {
            "label": "月營收",
            "live_providers": ["finmind", official_provider],
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready),
                    (official_provider, official_openapi_enabled),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fallback_enabled": official_openapi_enabled,
            "fallback_configured": official_openapi_enabled,
            "official_openapi_scope": "latest_reported_month_only",
            "redis_cache_ttl_seconds": settings.monthly_revenue_cache_ttl_seconds,
        },
        "financial_metrics": {
            "label": "五年財務",
            "live_providers": ["finmind", official_provider],
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready),
                    (official_provider, official_openapi_enabled),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fallback_enabled": official_openapi_enabled,
            "fallback_configured": official_openapi_enabled,
            "official_openapi_scope": "latest_quarter_income_balance_only",
            "redis_cache_ttl_seconds": settings.financial_metrics_cache_ttl_seconds,
        },
        "valuation": {
            "label": "估值",
            "live_providers": ["finmind", official_provider],
            "configured_providers": [
                provider
                for provider, configured in (
                    (finmind_provider_label, finmind_ready),
                    (official_provider, official_openapi_enabled),
                )
                if configured
            ],
            "finmind_access_mode": finmind_provider_label if finmind_ready else "disabled",
            "fallback_enabled": official_openapi_enabled,
            "fallback_configured": official_openapi_enabled,
            "official_openapi_scope": "latest_daily_valuation_only",
            "redis_cache_ttl_seconds": settings.valuation_metrics_cache_ttl_seconds,
        },
    }


def _market_data_provider_readiness(
    market_cache_status: dict,
    finmind_status: dict,
    fugle_status: dict,
) -> dict:
    provider_order = market_cache_status.get("price_provider_order") or []
    finmind_configured = bool(finmind_status.get("configured"))
    finmind_public_fallback_enabled = bool(finmind_status.get("public_fallback_enabled"))
    finmind_data_ready = bool(finmind_status.get("data_access_ready") or finmind_configured)
    fugle_configured = bool(fugle_status.get("configured"))
    official_openapi_enabled = bool(market_cache_status.get("official_openapi_fallback_enabled"))
    price_fallback_declared = "fugle" in provider_order
    price_fallback_configured = bool(price_fallback_declared and fugle_configured)
    price_rescue_configured = bool(price_fallback_configured or official_openapi_enabled)
    finmind_only_datasets = []
    blockers = []
    warnings = []
    if not finmind_data_ready:
        blockers.append("missing_finmind_access_for_monthly_revenue_financials_valuation")
    elif not finmind_configured and finmind_public_fallback_enabled:
        warnings.append("finmind_public_limited_mode_for_history_datasets")
    if price_fallback_declared and not fugle_configured:
        warnings.append("missing_fugle_api_key_for_price_fallback")
    if not price_fallback_declared:
        warnings.append("price_provider_order_lacks_fugle_fallback")
    if not price_rescue_configured:
        blockers.append("missing_price_rescue_provider")
    return {
        "ready": bool(finmind_data_ready and price_rescue_configured),
        "finmind_authenticated": finmind_configured,
        "finmind_public_fallback_enabled": finmind_public_fallback_enabled,
        "finmind_data_access_ready": finmind_data_ready,
        "finmind_access_mode": "authenticated"
        if finmind_configured
        else "public_limited"
        if finmind_public_fallback_enabled
        else "disabled",
        "fugle_price_fallback_configured": price_fallback_configured,
        "price_fallback_declared": price_fallback_declared,
        "price_rescue_configured": price_rescue_configured,
        "price_rescue_modes": [
            mode
            for mode, configured in (
                ("fugle_history", price_fallback_configured),
                ("official_openapi_latest_snapshot", official_openapi_enabled),
            )
            if configured
        ],
        "official_openapi_fallback_enabled": official_openapi_enabled,
        "official_openapi_fallback_scope": [
            "latest_price_snapshot",
            "latest_monthly_revenue",
            "latest_quarter_income_balance",
            "latest_daily_valuation",
        ]
        if official_openapi_enabled
        else [],
        "finmind_only_datasets": finmind_only_datasets,
        "full_history_datasets_requiring_finmind": [
            "monthly_revenue_history",
            "five_year_financial_metrics",
            "valuation_history",
        ],
        "official_openapi_latest_only_datasets": [
            "latest_price_snapshot",
            "latest_monthly_revenue",
            "latest_quarter_income_balance",
            "latest_daily_valuation",
        ]
        if official_openapi_enabled
        else [],
        "finmind_only_datasets_ready": finmind_data_ready,
        "warnings": warnings,
        "fallback_reason": ";".join(blockers) if blockers else None,
    }


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.password is None:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"
    return parsed._replace(netloc=netloc).geturl()
