from __future__ import annotations

from importlib.util import find_spec

from app.services.status_capability_helpers import capability as _capability
from app.services.status_graphrag import _neo4j_import_capability_status
from app.services.status_llm import _llm_fallback_readiness


def ai_rag_capabilities(
    *,
    vector_store: dict,
    llm_status: dict,
    llm_quota_routing: dict,
    llm_observability: dict,
    graph_status: dict,
    company_filing_status: dict,
) -> dict:
    embedding_status = vector_store.get("embedding_status") or {}
    retrieval_status = vector_store.get("retrieval_status") or {}
    reranker_status = vector_store.get("reranker_status") or {}

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
    neo4j_import = graph_status.get("neo4j_import") or {}

    return {
        "multilingual_embedding": _capability(
            "ready" if embedding_status.get("custom_embedding_enabled") else "degraded",
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
            "ready" if llm_sdk_ready and llm_fallback_ready else "degraded",
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
                "external_trace_configured": llm_observability.get("external_trace_configured"),
                "external_trace_ready": llm_observability.get("external_trace_ready"),
                "external_trace_missing_settings": llm_observability.get(
                    "external_trace_missing_settings"
                ),
                "external_trace_missing_dependencies": llm_observability.get(
                    "external_trace_missing_dependencies"
                ),
                "external_dispatch_enabled": llm_observability.get(
                    "external_dispatch_enabled"
                ),
                "trace_export_mode": llm_observability.get("trace_export_mode"),
                "trace_export_target": llm_observability.get("trace_export_target"),
                "trace_sink": llm_observability.get("trace_sink"),
                "langsmith_configured": llm_observability.get("langsmith_configured"),
                "phoenix_endpoint_configured": llm_observability.get(
                    "phoenix_endpoint_configured"
                ),
                "captured_fields": llm_observability.get("captured_fields"),
                "cost_tracking_enabled": llm_observability.get("cost_tracking_enabled"),
                "cost_rate_card_configured": llm_observability.get("cost_rate_card_configured"),
                "model_cost_rate_card_count": llm_observability.get("model_cost_rate_card_count"),
                "daily_cost_budget_usd": llm_observability.get("daily_cost_budget_usd"),
                "cost_warning_ratio": llm_observability.get("cost_warning_ratio"),
            },
            detail=(
                "Local traces capture LLM latency, token estimates, configurable cost estimates, "
                "retrieval latency, and reranker status; LangSmith/Phoenix sink profiles declare "
                "required settings/dependencies and keep local traces active when external sinks are pending."
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
                "mode_supported": company_filing_status.get("visual_rag_mode_supported"),
                "augment_policy": company_filing_status.get(
                    "visual_rag_augment_policy"
                ),
                "augment_policy_supported": company_filing_status.get(
                    "visual_rag_augment_policy_supported"
                ),
                "routing_policy": company_filing_status.get("visual_rag_routing_policy"),
                "runtime_available": company_filing_status.get("visual_rag_runtime_available"),
                "renderer_dependency_available": company_filing_status.get(
                    "visual_rag_renderer_dependency_available"
                ),
                "model": company_filing_status.get("visual_rag_model"),
                "model_supported": company_filing_status.get("visual_rag_model_supported"),
                "fallback_reason": company_filing_status.get("visual_rag_fallback_reason"),
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
                "agentic_cypher_plan_example": graph_status.get("agentic_cypher_plan_example"),
                "local_dry_run_enabled": graph_status.get(
                    "agentic_cypher_local_dry_run_enabled"
                ),
                "local_dry_run_status": graph_status.get(
                    "agentic_cypher_local_dry_run_status"
                ),
                "local_dry_run_mode": graph_status.get(
                    "agentic_cypher_local_dry_run_mode"
                ),
                "local_dry_run_row_count": graph_status.get(
                    "agentic_cypher_local_dry_run_row_count"
                ),
                "local_dry_run_evidence_policy": graph_status.get(
                    "agentic_cypher_local_dry_run_evidence_policy"
                ),
            },
            detail=(
                "LLM-generated Cypher is supported through a guarded planner that validates "
                "read-only operations, labels, relationship types, parameters, and path depth; "
                "a local in-memory dry-run validates plan semantics before Neo4j is configured."
            ),
        ),
        "neo4j_payload_export": _capability(
            "ready"
            if neo4j_import.get("payload_export_ready")
            else "degraded",
            evidence={
                "payload_export_ready": neo4j_import.get("payload_export_ready"),
                "payload_format": neo4j_import.get("payload_format"),
                "payload_node_count": neo4j_import.get("payload_node_count"),
                "payload_structural_edge_count": neo4j_import.get("payload_structural_edge_count"),
                "payload_peer_edge_count": neo4j_import.get("payload_peer_edge_count"),
                "payload_statement_count": neo4j_import.get("payload_statement_count"),
                "payload_export_endpoint": neo4j_import.get("payload_export_endpoint"),
                "payload_dry_run_cli": neo4j_import.get("payload_dry_run_cli"),
            },
            detail="Ready means GraphRAG can produce parameterized Neo4j Cypher payloads without requiring a live Neo4j connection.",
        ),
        "neo4j_import": _capability(
            _neo4j_import_capability_status(neo4j_import),
            evidence=neo4j_import,
            detail="External Neo4j import is ready only when URI, dependency, auth, and connection checks are available.",
        ),
        "graphrag_live_cypher_query": _capability(
            "ready"
            if neo4j_import.get("ready")
            and graph_status.get("agentic_cypher_planner_enabled")
            else "degraded",
            evidence={
                "endpoint": graph_status.get("agentic_cypher_live_query_endpoint"),
                "external_dependency": graph_status.get(
                    "agentic_cypher_live_query_external_dependency"
                ),
                "neo4j_ready": neo4j_import.get("ready"),
                "planner_enabled": graph_status.get("agentic_cypher_planner_enabled"),
                "local_dry_run_enabled": graph_status.get(
                    "agentic_cypher_local_dry_run_enabled"
                ),
                "local_dry_run_status": graph_status.get(
                    "agentic_cypher_local_dry_run_status"
                ),
                "local_dry_run_row_count": graph_status.get(
                    "agentic_cypher_local_dry_run_row_count"
                ),
                "plan_validation": (graph_status.get("agentic_cypher_plan_example") or {}).get(
                    "validation"
                ),
                "payload_dry_run_cli": neo4j_import.get("payload_dry_run_cli"),
                "smoke_cli": neo4j_import.get("smoke_cli"),
                "import_smoke_cli": neo4j_import.get("import_smoke_cli"),
            },
            detail=(
                "Live GraphRAG Cypher execution only runs server-generated guarded plans; "
                "without Neo4j it remains available as a validated plan plus clear degraded status."
            ),
        ),
    }


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False
