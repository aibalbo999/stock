from __future__ import annotations

from importlib.util import find_spec

from app.services.status_api_architecture import api_controller_status
from app.services.status_capability_architecture import architecture_capabilities
from app.services.status_capability_helpers import capability as _capability
from app.services.status_graphrag import _neo4j_import_capability_status
from app.services.status_llm import _llm_fallback_readiness
from app.services.status_market_data import _market_data_provider_readiness


def upgrade_capability_matrix(status: dict) -> dict:
    vector_store = status.get("vector_store") or {}
    embedding_status = vector_store.get("embedding_status") or {}
    retrieval_status = vector_store.get("retrieval_status") or {}
    reranker_status = vector_store.get("reranker_status") or {}
    llm_status = status.get("gemini") or {}
    llm_quota_routing = status.get("llm_quota_routing") or {}
    llm_observability = status.get("llm_observability") or {}
    graph_status = status.get("supply_chain_graph") or {}
    workflow_status = status.get("workflow_orchestration") or {}
    database_status = status.get("database") or {}
    migration_status = database_status.get("migration") or {}
    market_cache_status = status.get("market_data_cache") or {}
    company_filing_status = status.get("company_filings") or {}
    api_status = api_controller_status()
    frontend_status = status.get("frontend") or {}
    task_queue_status = status.get("task_queue") or {}
    python_runtime_status = status.get("python_runtime") or {}
    report_retention_status = status.get("report_retention") or {}
    security_scan_status = status.get("security_scanning") or {}
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
            "llm_quota_routing": _capability(
                "ready" if llm_quota_routing.get("ready") else "degraded",
                evidence=llm_quota_routing,
                detail=(
                    "Quota governance keeps the smartest configured report model first, tracks same-tier "
                    "Flash request budgets, skips exhausted models through hard routing/cooldown, and keeps "
                    "high-volume Gemma as the last text fallback."
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
            "llm_observability": _capability(
                "ready"
                if llm_observability.get("enabled")
                and llm_observability.get("local_trace_enabled")
                and "latency_ms" in (llm_observability.get("captured_fields") or [])
                and "total_token_estimate" in (llm_observability.get("captured_fields") or [])
                else "degraded",
                evidence={
                    "enabled": llm_observability.get("enabled"),
                    "provider": llm_observability.get("provider"),
                    "local_trace_enabled": llm_observability.get("local_trace_enabled"),
                    "external_trace_configured": llm_observability.get(
                        "external_trace_configured"
                    ),
                    "langsmith_configured": llm_observability.get("langsmith_configured"),
                    "phoenix_endpoint_configured": llm_observability.get(
                        "phoenix_endpoint_configured"
                    ),
                    "captured_fields": llm_observability.get("captured_fields"),
                    "cost_tracking_enabled": llm_observability.get("cost_tracking_enabled"),
                    "cost_rate_card_configured": llm_observability.get(
                        "cost_rate_card_configured"
                    ),
                    "model_cost_rate_card_count": llm_observability.get("model_cost_rate_card_count"),
                    "daily_cost_budget_usd": llm_observability.get("daily_cost_budget_usd"),
                    "cost_warning_ratio": llm_observability.get("cost_warning_ratio"),
                },
                detail=(
                    "Local traces capture LLM latency, token estimates, configurable cost estimates, "
                    "retrieval latency, and reranker status; LangSmith/Phoenix are optional external sinks."
                ),
            ),
            "visual_rag": _capability(
                "ready"
                if company_filing_status.get("visual_rag_enabled")
                and company_filing_status.get("visual_rag_runtime_available")
                else "not_configured",
                evidence={
                    "enabled": company_filing_status.get("visual_rag_enabled"),
                    "mode": company_filing_status.get("visual_rag_mode"),
                    "runtime_available": company_filing_status.get(
                        "visual_rag_runtime_available"
                    ),
                    "renderer_dependency_available": company_filing_status.get(
                        "visual_rag_renderer_dependency_available"
                    ),
                    "model": company_filing_status.get("visual_rag_model"),
                    "max_pages": company_filing_status.get("visual_rag_max_pages"),
                    "dpi": company_filing_status.get("visual_rag_dpi"),
                    "runtime": company_filing_status.get("visual_rag_runtime"),
                },
                detail=(
                    "Optional Visual RAG fallback/augmentation converts PDF pages to images and "
                    "uses a vision-capable LLM to preserve complex financial tables."
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
            "graphrag_path_reasoning": _capability(
                "ready"
                if graph_status.get("path_reasoning_enabled")
                and graph_status.get("shortest_path_context_enabled")
                else "degraded",
                evidence={
                    "path_reasoning_enabled": graph_status.get("path_reasoning_enabled"),
                    "shortest_path_context_enabled": graph_status.get(
                        "shortest_path_context_enabled"
                    ),
                    "path_reasoning_strategy": graph_status.get("path_reasoning_strategy"),
                    "path_reasoning_evidence_policy": graph_status.get(
                        "path_reasoning_evidence_policy"
                    ),
                    "path_reasoning_example": graph_status.get("path_reasoning_example"),
                    "path_reasoning_endpoint": graph_status.get("path_reasoning_endpoint"),
                    "neo4j_shortest_path_template": graph_status.get(
                        "neo4j_shortest_path_template"
                    ),
                },
                detail="GraphRAG can compute shortest-path impact context for LLM reasoning while preserving evidence guardrails.",
            ),
            "graphrag_agentic_cypher": _capability(
                "ready"
                if graph_status.get("agentic_cypher_planner_enabled")
                and (graph_status.get("agentic_cypher_plan_example") or {})
                .get("validation", {})
                .get("valid")
                else "degraded",
                evidence={
                    "agentic_cypher_planner_enabled": graph_status.get(
                        "agentic_cypher_planner_enabled"
                    ),
                    "agentic_cypher_strategy": graph_status.get("agentic_cypher_strategy"),
                    "agentic_cypher_endpoint": graph_status.get("agentic_cypher_endpoint"),
                    "agentic_cypher_guardrails": graph_status.get("agentic_cypher_guardrails"),
                    "agentic_cypher_plan_example": graph_status.get(
                        "agentic_cypher_plan_example"
                    ),
                },
                detail=(
                    "LLM-generated Cypher is supported through a guarded planner that validates "
                    "read-only operations, labels, relationship types, parameters, and path depth."
                ),
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
            "graphrag_live_cypher_query": _capability(
                "ready"
                if (graph_status.get("neo4j_import") or {}).get("ready")
                and graph_status.get("agentic_cypher_planner_enabled")
                else "degraded",
                evidence={
                    "endpoint": graph_status.get("agentic_cypher_live_query_endpoint"),
                    "external_dependency": graph_status.get(
                        "agentic_cypher_live_query_external_dependency"
                    ),
                    "neo4j_ready": (graph_status.get("neo4j_import") or {}).get("ready"),
                    "planner_enabled": graph_status.get("agentic_cypher_planner_enabled"),
                    "plan_validation": (
                        graph_status.get("agentic_cypher_plan_example") or {}
                    ).get("validation"),
                },
                detail=(
                    "Live GraphRAG Cypher execution only runs server-generated guarded plans; "
                    "without Neo4j it remains available as a validated plan plus clear degraded status."
                ),
            ),
        },
        "architecture": architecture_capabilities(
            api_status=api_status,
            workflow_status=workflow_status,
            task_queue_status=task_queue_status,
            frontend_status=frontend_status,
            python_runtime_status=python_runtime_status,
            database_status=database_status,
            migration_status=migration_status,
            security_scan_status=security_scan_status,
        ),
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
                    "browser_render_configured": company_filing_status.get("browser_render_configured"),
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
            "company_filing_structured_api_fallback": _capability(
                "ready"
                if company_filing_status.get("structured_api_configured")
                else "not_configured",
                evidence={
                    "configured": company_filing_status.get("structured_api_configured"),
                    "provider": company_filing_status.get("structured_api_provider"),
                    "url_configured": company_filing_status.get("structured_api_url_configured"),
                    "token_configured": company_filing_status.get("structured_api_token_configured"),
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


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False
