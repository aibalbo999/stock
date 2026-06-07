from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

import redis

from app.core.config import get_settings
from app.data_sources.company_filings import (
    company_filing_browser_render_status,
    company_filing_playwright_browser_status,
    company_filing_structured_api_status,
)
from app.db.migration_status import db_migration_status
from app.db.session import engine
from app.services.candidate_confidence import confidence_thresholds
from app.services.llm_client import RETRYABLE_HTTP_STATUSES
from app.services.llm_observability import llm_observability_status
from app.services.source_quality import SOURCE_CREDIBILITY_LABELS, SOURCE_CREDIBILITY_WEIGHTS
from app.services.status_company_filings import (
    company_filing_status as collect_company_filing_status,
)
from app.services.status_frontend import frontend_status as collect_frontend_status
from app.services.status_llm import (
    _llm_effective_fallback_models,
    _llm_fallback_readiness,
    _llm_model_provider,
    _llm_quota_routing_status,
)
from app.services.status_graphrag import (
    _neo4j_import_capability_status,
    supply_chain_graph_status as collect_supply_chain_graph_status,
)
from app.services.status_market_data import (
    _market_data_provider_readiness,
    market_data_status as collect_market_data_status,
)
from app.services.status_vector_store import vector_store_status as collect_vector_store_status
from app.services.visual_rag import visual_rag_status
from app.services.workflow_orchestration import workflow_orchestration_status


def service_status() -> dict:
    settings = get_settings()
    high_threshold, medium_threshold = confidence_thresholds()
    redis_status = _redis_status(settings.redis_url)
    llm_fallback_models = _llm_effective_fallback_models(settings)
    llm_local_gateway_configured = any(
        _llm_model_provider(model) == "local" for model in llm_fallback_models
    )
    llm_quota_routing = _llm_quota_routing_status(settings)
    llm_observability = llm_observability_status(settings)
    visual_rag_runtime = visual_rag_status(settings)
    market_data_status = collect_market_data_status(settings, redis_status=redis_status)
    supply_chain_graph_status = collect_supply_chain_graph_status()
    vector_store_status = collect_vector_store_status(
        settings,
        module_available=_module_available,
    )
    company_filing_status = collect_company_filing_status(
        settings,
        redis_status=redis_status,
        visual_rag_runtime=visual_rag_runtime,
        module_available=_module_available,
        browser_render_status_func=company_filing_browser_render_status,
        playwright_browser_status_func=company_filing_playwright_browser_status,
        structured_api_status_func=company_filing_structured_api_status,
    )
    frontend_status = collect_frontend_status()
    python_runtime_status = _python_runtime_status()
    report_retention_status = _report_retention_status()
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
        "frontend": frontend_status,
        "python_runtime": python_runtime_status,
        "report_retention": report_retention_status,
        "llm_quota_routing": llm_quota_routing,
        "llm_observability": llm_observability,
        "finmind": market_data_status["finmind"],
        "fugle": market_data_status["fugle"],
        "market_data_cache": market_data_status["market_data_cache"],
        "company_filings": company_filing_status,
        "vector_store": vector_store_status,
        "supply_chain_graph": supply_chain_graph_status,
        "celery": {
            "broker_url": _redact_url(settings.redis_url),
            "backend_url": _redact_url(settings.redis_url),
        },
        "workflow_orchestration": workflow_orchestration_status(settings),
        "security_scanning": _security_scan_status(),
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
    llm_quota_routing = status.get("llm_quota_routing") or {}
    llm_observability = status.get("llm_observability") or {}
    graph_status = status.get("supply_chain_graph") or {}
    workflow_status = status.get("workflow_orchestration") or {}
    database_status = status.get("database") or {}
    migration_status = database_status.get("migration") or {}
    market_cache_status = status.get("market_data_cache") or {}
    company_filing_status = status.get("company_filings") or {}
    api_status = _api_controller_status()
    frontend_status = status.get("frontend") or {}
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
        "architecture": {
            "thin_api_controller": _capability(
                "ready"
                if (api_status.get("main_py_lines") or 10_000) <= 220
                and api_status["route_module_count"] >= 7
                and api_status.get("app_factory_present")
                and api_status.get("main_uses_app_factory")
                and api_status.get("compatibility_exports_present")
                and api_status.get("main_uses_compatibility_exports")
                and api_status.get("compatibility_helpers_present")
                and api_status.get("main_uses_compatibility_helpers")
                and api_status.get("compatibility_service_present")
                and api_status.get("api_runtime_present")
                and api_status.get("main_uses_api_runtime")
                and api_status.get("task_uses_api_runtime")
                and api_status.get("task_exports_present")
                and api_status.get("api_runtime_uses_task_exports")
                and not api_status.get("task_imports_api_main")
                and not api_status.get("compatibility_exports_imports_tasks")
                and api_status.get("main_direct_domain_import_count") == 0
                and not api_status.get("main_imports_legacy_facade")
                else "degraded",
                evidence=api_status,
                detail=(
                    "FastAPI main is a thin app entry; routers, app assembly, legacy helper exports, "
                    "and use-case services live in separate modules."
                ),
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
            "streamlit_mpa_background_tasks": _capability(
                "ready"
                if frontend_status.get("streamlit_entry_uses_navigation")
                and int(frontend_status.get("page_count") or 0) >= 4
                and frontend_status.get("expected_pages_present")
                and frontend_status.get("external_css_loaded")
                and frontend_status.get("external_report_css_loaded")
                and frontend_status.get("report_html_renderer_extracted")
                and frontend_status.get("ui_status_helpers_extracted")
                and frontend_status.get("ui_api_client_extracted")
                and frontend_status.get("ui_task_status_panel_extracted")
                and frontend_status.get("ui_report_state_extracted")
                and frontend_status.get("ui_report_panels_extracted")
                and frontend_status.get("ui_report_follow_up_controls_extracted")
                and frontend_status.get("ui_report_markdown_helpers_extracted")
                and frontend_status.get("ui_report_candidate_audit_extracted")
                and frontend_status.get("ui_report_formatters_extracted")
                and frontend_status.get("ui_report_sections_extracted")
                and frontend_status.get("ui_wildcard_imports_removed")
                and frontend_status.get("uses_task_enqueue_helper")
                and frontend_status.get("uses_task_status_panel")
                and frontend_status.get("asyncio_run_count") == 0
                and not frontend_status.get("long_blocking_post_timeout_present")
                and not frontend_status.get("sync_report_generate_used")
                else "degraded",
                evidence=frontend_status,
                detail=(
                    "Streamlit uses a multi-page shell, explicit page imports, external CSS, "
                    "extracted API/task/report helpers, and FastAPI/Celery task enqueue/status "
                    "polling instead of running long ingestion/report calls inline."
                ),
            ),
            "python_runtime": _capability(
                "ready"
                if python_runtime_status.get("current_runtime_supported")
                and python_runtime_status.get("project_targets_aligned")
                else "degraded",
                evidence=python_runtime_status,
                detail=(
                    "Runtime preflight compares the active Python interpreter with the "
                    "project's Python 3.11+ target declared in pyproject, .python-version, CI, and Docker."
                ),
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
            "secret_scanning": _capability(
                "ready"
                if security_scan_status.get("external_engine_integration")
                and security_scan_status.get("detect_secrets_dependency_declared")
                and security_scan_status.get("local_regex_fallback_enabled")
                else "degraded",
                evidence=security_scan_status,
                detail=(
                    "Secret scanning prefers external tools such as detect-secrets/gitleaks "
                    "and keeps local regex only as a fallback."
                ),
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


def _capability(state: str, *, evidence: dict, detail: str | None = None) -> dict:
    payload = {
        "status": state,
        "evidence": evidence,
    }
    if detail:
        payload["detail"] = detail
    return payload


def _api_controller_status() -> dict:
    app_dir = Path(__file__).resolve().parents[1]
    api_dir = app_dir / "api"
    main_path = api_dir / "main.py"
    runtime_path = api_dir / "runtime.py"
    tasks_path = app_dir / "tasks" / "tasks.py"
    main_source = ""
    runtime_source = ""
    tasks_source = ""
    try:
        main_source = main_path.read_text(encoding="utf-8")
        main_py_lines = len(main_source.splitlines())
    except OSError:
        main_py_lines = None
    try:
        runtime_source = runtime_path.read_text(encoding="utf-8")
    except OSError:
        runtime_source = ""
    try:
        tasks_source = tasks_path.read_text(encoding="utf-8")
    except OSError:
        tasks_source = ""
    route_modules = sorted(path.name for path in api_dir.glob("*_routes.py"))
    legacy_facade_path = api_dir / "legacy_facade.py"
    compatibility_exports_path = api_dir / "compatibility_exports.py"
    compatibility_helpers_path = api_dir / "compatibility_helpers.py"
    task_exports_path = api_dir / "task_exports.py"
    try:
        compatibility_exports_source = compatibility_exports_path.read_text(encoding="utf-8")
    except OSError:
        compatibility_exports_source = ""
    try:
        legacy_facade_source = legacy_facade_path.read_text(encoding="utf-8")
    except OSError:
        legacy_facade_source = ""
    direct_domain_imports = [
        line.strip()
        for line in main_source.splitlines()
        if (
            line.startswith("from app.data_sources.")
            or line.startswith("from app.db.")
            or line.startswith("from app.models.")
            or line.startswith("from app.rag.")
            or line.startswith("from app.tasks.")
            or (
                line.startswith("from app.services.")
                and "app.services.api_compatibility" not in line
            )
        )
    ]
    return {
        "main_py_lines": main_py_lines,
        "route_module_count": len(route_modules),
        "route_modules": route_modules,
        "app_factory_present": (api_dir / "app_factory.py").exists(),
        "main_uses_app_factory": "from app.api.app_factory import create_app" in main_source,
        "service_factory_present": (api_dir / "service_factory.py").exists(),
        "api_runtime_present": runtime_path.exists(),
        "main_uses_api_runtime": "build_api_runtime" in main_source,
        "task_uses_api_runtime": "get_task_api_services" in tasks_source,
        "task_imports_api_main": "app.api.main" in tasks_source,
        "compatibility_exports_present": compatibility_exports_path.exists(),
        "main_uses_compatibility_exports": (
            "compatibility_export_namespace" in main_source
            or (
                "build_api_runtime" in main_source
                and "compatibility_exports" in main_source
                and "compatibility_export_namespace" in runtime_source
            )
        ),
        "compatibility_helpers_present": compatibility_helpers_path.exists(),
        "main_uses_compatibility_helpers": (
            "compatibility_helper_namespace" in main_source
            or (
                "build_api_runtime" in main_source
                and "compatibility_helpers" in main_source
                and "compatibility_helper_namespace" in runtime_source
            )
        ),
        "task_exports_present": task_exports_path.exists(),
        "api_runtime_uses_task_exports": "task_export_namespace" in runtime_source,
        "compatibility_exports_imports_tasks": "from app.tasks." in compatibility_exports_source,
        "main_direct_domain_import_count": len(direct_domain_imports),
        "main_direct_domain_imports": direct_domain_imports,
        "compatibility_service_present": (app_dir / "services" / "api_compatibility.py").exists(),
        "main_imports_legacy_facade": "app.api.legacy_facade" in main_source
        or "LegacyApiFacade" in main_source,
        "legacy_facade_present": legacy_facade_path.exists(),
        "legacy_facade_alias_only": "ApiCompatibilityService" in legacy_facade_source
        and "class LegacyApiFacade(ApiCompatibilityService)" in legacy_facade_source,
    }


def _python_runtime_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    pyproject_text = _read_text(root / "pyproject.toml")
    python_version_text = _read_text(root / ".python-version").strip()
    ci_text = _read_text(root / ".github" / "workflows" / "ci.yml")
    dockerfile_text = _read_text(root / "Dockerfile")
    required_specifier = _pyproject_requires_python(pyproject_text)
    minimum_supported = _minimum_python_from_requires(required_specifier)
    current_version = ".".join(str(part) for part in sys.version_info[:3])
    current_major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    current_supported = (
        sys.version_info[:2] >= minimum_supported if minimum_supported is not None else True
    )
    target_version = (
        f"{minimum_supported[0]}.{minimum_supported[1]}" if minimum_supported else ""
    )
    ci_targets_python = bool(target_version and f'python-version: "{target_version}"' in ci_text)
    docker_targets_python = bool(target_version and f"python:{target_version}" in dockerfile_text)
    python_version_file_matches = python_version_text == target_version if target_version else False
    project_targets_aligned = bool(
        target_version and ci_targets_python and docker_targets_python and python_version_file_matches
    )
    return {
        "current_version": current_version,
        "current_major_minor": current_major_minor,
        "implementation": sys.implementation.name,
        "executable": sys.executable,
        "required_specifier": required_specifier,
        "minimum_supported": target_version,
        "current_runtime_supported": current_supported,
        "python_version_file": python_version_text,
        "python_version_file_matches": python_version_file_matches,
        "ci_targets_python": ci_targets_python,
        "docker_targets_python": docker_targets_python,
        "project_targets_aligned": project_targets_aligned,
        "bootstrap_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --apply --replace-existing",
        "bootstrap_dry_run_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --json",
        "bootstrap_backup_policy": "Unsupported existing .venv is moved to .venv.backup-<timestamp> only with --replace-existing.",
        "interpreter_install_hints": _python_interpreter_install_hints(target_version),
        "recommended_action": (
            "Install a supported Python interpreter if needed, then rebuild .venv with "
            f"Python {target_version}+ before production startup."
            if target_version and not current_supported
            else None
        ),
    }


def _python_interpreter_install_hints(target_version: str) -> list[dict[str, str]]:
    version = str(target_version or "").strip()
    if not version:
        return []
    return [
        {
            "tool": "homebrew",
            "command": f"brew install python@{version}",
            "venv_command": f"python{version} -m venv .venv",
        },
        {
            "tool": "pyenv",
            "command": f"pyenv install {version}",
            "venv_command": f"pyenv local {version} && python -m venv .venv",
        },
        {
            "tool": "uv",
            "command": f"uv python install {version}",
            "venv_command": f"uv venv --python {version} .venv",
        },
    ]


def _pyproject_requires_python(pyproject_text: str) -> str:
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("requires-python"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _minimum_python_from_requires(specifier: str) -> tuple[int, int] | None:
    marker = ">="
    if marker not in specifier:
        return None
    version = specifier.split(marker, 1)[1].split(",", 1)[0].strip()
    parts = version.split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _report_retention_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    persistence_source = _read_text(root / "app" / "services" / "persistence.py")
    report_files_source = _read_text(root / "app" / "services" / "report_files.py")
    report_query_source = _read_text(root / "app" / "services" / "report_query.py")
    data_operations_source = _read_text(root / "app" / "services" / "data_operations_api.py")
    maintenance_ui_source = _read_text(
        root / "app" / "ui" / "system_settings_maintenance.py"
    )
    write_prunes_db = "self.prune_older_for_topic(report.topic, report.id)" in persistence_source
    report_file_write_prunes = (
        "prune_report_files_for_topic(report_dir, safe_topic, keep_path=path)"
        in report_files_source
    )
    return {
        "policy": "latest_per_topic",
        "write_prunes_db_by_topic": write_prunes_db,
        "write_prunes_markdown_by_topic": report_file_write_prunes,
        "repository_latest_by_topic_available": "def latest_by_topic(" in persistence_source
        and "seen_topics" in persistence_source,
        "repository_bulk_prune_available": "def prune_older_by_topic(" in persistence_source,
        "repository_topic_prune_available": "def prune_older_for_topic(" in persistence_source,
        "run_links_cleared_for_pruned_reports": ".values(report_id=None)" in persistence_source,
        "markdown_bulk_prune_available": "def prune_older_report_files_by_topic(" in report_files_source,
        "markdown_topic_key_parser_available": "def report_file_topic_key(" in report_files_source,
        "list_reports_uses_latest_by_topic": "latest_by_topic(limit)" in report_query_source,
        "quality_summary_uses_latest_by_topic": "latest_by_topic(safe_limit)"
        in report_query_source,
        "report_list_returns_policy": '"retention_policy": "latest_per_topic"'
        in report_query_source,
        "maintenance_prunes_db_by_topic": "reports.prune_older_by_topic()"
        in data_operations_source,
        "maintenance_prunes_markdown_by_topic": "self._prune_older_report_files()"
        in data_operations_source
        and "prune_older_report_files_by_topic" in data_operations_source,
        "maintenance_returns_policy": '"report_retention_policy": "latest_per_topic"'
        in data_operations_source,
        "settings_ui_cleanup_action": '"latest_reports_only": True' in maintenance_ui_source
        and '"orphan_report_refs": True' in maintenance_ui_source,
        "covered_paths": [
            "app/services/persistence.py",
            "app/services/report_files.py",
            "app/services/report_query.py",
            "app/services/data_operations_api.py",
            "app/ui/system_settings_maintenance.py",
        ],
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _security_scan_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "security_scan.py"
    pyproject_path = root / "pyproject.toml"
    try:
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        pyproject_text = ""
    detect_secrets_cli = shutil.which("detect-secrets") is not None
    gitleaks_cli = shutil.which("gitleaks") is not None
    default_engine = (
        "detect-secrets"
        if detect_secrets_cli
        else "gitleaks"
        if gitleaks_cli
        else "local_regex"
    )
    return {
        "script": str(script_path.relative_to(root)),
        "pyproject_command_configured": "scripts/security_scan.py" in pyproject_text,
        "external_engine_integration": True,
        "supported_external_engines": ["detect-secrets", "gitleaks"],
        "detect_secrets_dependency_declared": "detect-secrets" in pyproject_text,
        "detect_secrets_cli_available": detect_secrets_cli,
        "detect_secrets_module_available": _module_available("detect_secrets"),
        "gitleaks_cli_available": gitleaks_cli,
        "default_engine": default_engine,
        "local_regex_fallback_enabled": script_path.exists(),
        "local_regex_fallback_role": "fallback_only",
        "scan_scope_default": "git_tracked_files",
        "all_files_flag": "--all",
    }


def _redis_status(redis_url: str) -> dict:
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        pong = client.ping()
        return {"ok": bool(pong), "url": _redact_url(redis_url)}
    except Exception as exc:
        return {"ok": False, "url": _redact_url(redis_url), "error": str(exc)}


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
