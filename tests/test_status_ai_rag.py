from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.service_status import service_status
from app.services.status_graphrag import _neo4j_import_capability_status


def test_vector_store_and_graphrag_status_shape_and_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    service_status_source = Path("app/services/service_status.py").read_text()
    status_graphrag_source = Path("app/services/status_graphrag.py").read_text()
    status_vector_store_source = Path("app/services/status_vector_store.py").read_text()

    assert "chroma_available" in status["vector_store"]
    assert status["vector_store"]["storage_mode"] in {"persistent", "http"}
    assert status["vector_store"]["chroma_api_url_configured"] == bool(Settings().chroma_api_url)
    assert status["vector_store"]["embedding_provider"] == Settings().rag_embedding_provider
    assert status["vector_store"]["embedding_model"] == Settings().rag_embedding_model
    assert status["vector_store"]["allow_chroma_default_embedding_fallback"] is False
    expected_persistent_collection = bool(
        Settings().use_chroma
        and status["vector_store"]["chroma_available"]
        and (
            not status["vector_store"]["embedding_status"].get("custom_embedding_requested")
            or status["vector_store"]["embedding_status"].get("custom_embedding_enabled")
            or Settings().rag_allow_chroma_default_embedding_fallback
        )
    )
    assert status["vector_store"]["persistent_collection_enabled"] is expected_persistent_collection
    assert status["vector_store"]["embedding_status"]["provider"] == Settings().rag_embedding_provider
    assert "custom_embedding_enabled" in status["vector_store"]["embedding_status"]
    assert status["vector_store"]["embedding_status"]["chroma_default_fallback_allowed"] is False
    assert "fallback_reason" in status["vector_store"]["embedding_status"]
    assert status["vector_store"]["retrieval_status"]["strategy"] == "hybrid-vector-bm25"
    assert status["vector_store"]["retrieval_status"]["bm25_enabled"] is True
    assert (
        status["vector_store"]["retrieval_status"]["tokenizer"]
        == "latin_terms+traditional_chinese_2_4_ngrams"
    )
    assert status["vector_store"]["retrieval_status"]["embedding_identity_header_enabled"] is True
    assert status["vector_store"]["retrieval_status"]["retrieval_trace_enabled"] is True
    assert "final_score" in status["vector_store"]["retrieval_status"]["retrieval_trace_fields"]
    assert "entity_tickers" in status["vector_store"]["retrieval_status"]["keyword_identity_fields"]
    assert "entity_names" in status["vector_store"]["retrieval_status"]["keyword_identity_fields"]
    assert (
        status["vector_store"]["retrieval_status"]["index_schema_version"]
        == Settings().rag_index_schema_version
    )
    assert "identity_v2" in status["vector_store"]["retrieval_status"]["collection_name_example"]
    assert (
        status["vector_store"]["retrieval_status"]["keyword_corpus_limit"]
        == Settings().rag_keyword_corpus_limit
    )
    assert status["vector_store"]["hybrid_search_enabled"] is True
    assert status["vector_store"]["keyword_corpus_limit"] == Settings().rag_keyword_corpus_limit
    assert status["vector_store"]["reranker_provider"] == Settings().rag_reranker_provider
    assert status["vector_store"]["reranker_model"] == Settings().rag_reranker_model
    assert status["vector_store"]["reranker_available"] is True
    assert status["vector_store"]["reranker_status"]["normalized_provider"] == "auto"
    assert status["vector_store"]["reranker_status"]["resolved_provider"] in {"llm", "keyword"}
    if status["vector_store"]["reranker_status"]["resolved_provider"] == "llm":
        assert status["vector_store"]["reranker_status"]["execution_mode"] == "llm_rerank"
        assert status["vector_store"]["reranker_status"]["quality_tier"] == "llm_model_reranker"
        assert status["vector_store"]["reranker_status"]["keyword_fallback"] is False
        assert status["vector_store"]["reranker_status"]["model_reranker_ready"] is True
    else:
        assert status["vector_store"]["reranker_status"]["execution_mode"] == "keyword"
        assert status["vector_store"]["reranker_status"]["quality_tier"] == "lexical_fallback"
        assert status["vector_store"]["reranker_status"]["keyword_fallback"] is True
        assert status["vector_store"]["reranker_status"]["model_reranker_ready"] is False
        assert status["vector_store"]["reranker_status"]["model_reranker_gap"].startswith(
            "auto_model_reranker_unavailable:"
        )
    assert status["vector_store"]["reranker_status"]["fallback_reason"] is None
    assert status["vector_store"]["collector_path"] == "app/services/status_vector_store.py"
    assert (
        "from app.services.status_vector_store import vector_store_status as collect_vector_store_status"
        in service_status_source
    )
    assert "def _vector_store_persistent_collection_enabled(" not in service_status_source
    assert "def vector_store_status(" in status_vector_store_source

    assert status["supply_chain_graph"]["enabled"] is True
    assert status["supply_chain_graph"]["node_count"] >= 1
    assert status["supply_chain_graph"]["edge_confidence"] == "taxonomy"
    assert status["supply_chain_graph"]["query_expansion_enabled"] is True
    assert status["supply_chain_graph"]["retrieval_hints_enabled"] is True
    assert status["supply_chain_graph"]["retrieval_query_plan_enabled"] is True
    assert (
        status["supply_chain_graph"]["retrieval_query_strategy"]
        == "taxonomy_graph_query_expansion"
    )
    assert "corroborated" in status["supply_chain_graph"]["retrieval_evidence_policy"]
    assert status["supply_chain_graph"]["retrieval_query_example"]
    assert status["supply_chain_graph"]["collector_path"] == "app/services/status_graphrag.py"
    assert "from app.services.status_graphrag import (" in service_status_source
    assert "def _supply_chain_graph_status(" not in service_status_source
    assert "def supply_chain_graph_status(" in status_graphrag_source
    assert status["supply_chain_graph"]["neo4j_export_enabled"] is True
    assert status["supply_chain_graph"]["neo4j_import"]["ready"] is False
    assert (
        status["supply_chain_graph"]["neo4j_import"]["fallback_reason"]
        == "missing_settings:neo4j_uri"
    )
    assert status["supply_chain_graph"]["neo4j_import"]["payload_export_ready"] is True
    assert status["supply_chain_graph"]["neo4j_import"]["payload_format"] == "neo4j_cypher_v1"
    assert status["supply_chain_graph"]["neo4j_import"]["payload_node_count"] >= 1
    assert status["supply_chain_graph"]["neo4j_import"]["payload_statement_count"] >= 1
    assert status["supply_chain_graph"]["neo4j_import"]["smoke_cli"].endswith(
        "scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
    )
    assert "--import-first" in status["supply_chain_graph"]["neo4j_import"]["import_smoke_cli"]
    assert status["supply_chain_graph"]["path_reasoning_enabled"] is True
    assert status["supply_chain_graph"]["shortest_path_context_enabled"] is True
    assert (
        status["supply_chain_graph"]["path_reasoning_strategy"]
        == "taxonomy_graph_shortest_path_reasoning"
    )
    assert status["supply_chain_graph"]["path_reasoning_endpoint"] == (
        "GET /supply-chain/graph/reasoning"
    )
    assert "shortestPath" in status["supply_chain_graph"]["neo4j_shortest_path_template"]


def test_visual_rag_status_shape_and_capability_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    matrix = status["upgrade_capability_matrix"]

    assert status["company_filings"]["visual_rag_enabled"] is Settings().company_filing_visual_rag_enabled
    assert status["company_filings"]["visual_rag_mode"] == Settings().company_filing_visual_rag_mode
    assert isinstance(status["company_filings"]["visual_rag_mode_supported"], bool)
    assert isinstance(status["company_filings"]["visual_rag_runtime_available"], bool)
    assert status["company_filings"]["visual_rag_model"] == Settings().company_filing_visual_rag_model
    assert isinstance(status["company_filings"]["visual_rag_model_supported"], bool)
    assert status["company_filings"]["visual_rag_max_pages"] == Settings().company_filing_visual_rag_max_pages
    assert status["company_filings"]["visual_rag_dpi"] == 144
    assert status["company_filings"]["visual_rag_fallback_reason"] == status["company_filings"][
        "visual_rag_runtime"
    ].get("fallback_reason")
    assert "fallback_reason" in status["company_filings"]["visual_rag_runtime"]

    expected_visual_rag_status = (
        "ready"
        if status["company_filings"]["visual_rag_runtime_available"]
        else "not_configured"
    )
    assert matrix["ai_rag"]["visual_rag"]["status"] == expected_visual_rag_status
    assert (
        matrix["ai_rag"]["visual_rag"]["evidence"]["enabled"]
        is status["company_filings"]["visual_rag_enabled"]
    )
    assert (
        matrix["ai_rag"]["visual_rag"]["evidence"]["mode_supported"]
        is status["company_filings"]["visual_rag_mode_supported"]
    )
    assert (
        matrix["ai_rag"]["visual_rag"]["evidence"]["model_supported"]
        is status["company_filings"]["visual_rag_model_supported"]
    )
    assert (
        matrix["ai_rag"]["visual_rag"]["evidence"]["runtime_available"]
        is status["company_filings"]["visual_rag_runtime_available"]
    )
    assert matrix["ai_rag"]["visual_rag"]["evidence"]["fallback_reason"] == status[
        "company_filings"
    ]["visual_rag_fallback_reason"]
    assert "fallback_reason" in matrix["ai_rag"]["visual_rag"]["evidence"]["runtime"]


def test_visual_rag_capability_rejects_non_vision_report_model(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_MODE", "fallback")
    monkeypatch.setenv("COMPANY_FILING_VISUAL_RAG_MODEL", "imagen-4-ultra-generate")
    monkeypatch.setenv("GOOGLE_API_KEY", "key")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.visual_rag._module_available", lambda name: name == "fitz")
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    visual_rag = status["upgrade_capability_matrix"]["ai_rag"]["visual_rag"]

    assert status["company_filings"]["visual_rag_mode_supported"] is True
    assert status["company_filings"]["visual_rag_model_supported"] is False
    assert status["company_filings"]["visual_rag_runtime_available"] is False
    assert status["company_filings"]["visual_rag_fallback_reason"] == "unsupported_visual_rag_model"
    assert visual_rag["status"] == "not_configured"
    assert visual_rag["evidence"]["model"] == "imagen-4-ultra-generate"
    assert visual_rag["evidence"]["model_supported"] is False
    assert visual_rag["evidence"]["fallback_reason"] == "unsupported_visual_rag_model"


def test_ai_rag_capability_matrix_evidence(service_status_snapshot) -> None:
    status = service_status_snapshot
    matrix = status["upgrade_capability_matrix"]

    assert matrix["ai_rag"]["hybrid_search"]["status"] == "ready"
    assert matrix["ai_rag"]["hybrid_search"]["evidence"]["retrieval_trace_enabled"] is True
    expected_reranking_status = (
        "ready"
        if status["vector_store"]["reranker_status"]["model_reranker_ready"]
        else "degraded"
    )
    assert matrix["ai_rag"]["reranking"]["status"] == expected_reranking_status
    assert matrix["ai_rag"]["reranking"]["evidence"]["configured_provider"] == "auto"
    assert matrix["ai_rag"]["reranking"]["evidence"]["resolved_provider"] in {"llm", "keyword"}
    assert matrix["ai_rag"]["reranking"]["evidence"]["available"] is True
    assert (
        matrix["ai_rag"]["reranking"]["evidence"]["model_reranker_ready"]
        is status["vector_store"]["reranker_status"]["model_reranker_ready"]
    )
    assert (
        matrix["ai_rag"]["reranking"]["evidence"]["keyword_fallback"]
        is status["vector_store"]["reranker_status"]["keyword_fallback"]
    )
    assert matrix["ai_rag"]["reranking"]["evidence"]["auto_candidates"]

    assert matrix["ai_rag"]["graphrag_context"]["status"] == "ready"
    assert matrix["ai_rag"]["graphrag_context"]["evidence"]["retrieval_query_plan_enabled"] is True
    assert (
        matrix["ai_rag"]["graphrag_context"]["evidence"]["retrieval_query_strategy"]
        == "taxonomy_graph_query_expansion"
    )
    assert matrix["ai_rag"]["graphrag_path_reasoning"]["status"] == "ready"
    assert (
        matrix["ai_rag"]["graphrag_path_reasoning"]["evidence"]["path_reasoning_strategy"]
        == "taxonomy_graph_shortest_path_reasoning"
    )
    assert (
        matrix["ai_rag"]["graphrag_path_reasoning"]["evidence"]["path_reasoning_endpoint"]
        == "GET /supply-chain/graph/reasoning"
    )
    assert (
        "shortestPath"
        in matrix["ai_rag"]["graphrag_path_reasoning"]["evidence"]["neo4j_shortest_path_template"]
    )
    assert matrix["ai_rag"]["graphrag_agentic_cypher"]["status"] == "ready"
    cypher_evidence = matrix["ai_rag"]["graphrag_agentic_cypher"]["evidence"]
    assert cypher_evidence["agentic_cypher_planner_enabled"] is True
    assert cypher_evidence["agentic_cypher_strategy"] == "guarded_llm_cypher_planner"
    assert cypher_evidence["agentic_cypher_endpoint"] == "GET /supply-chain/graph/cypher-plan"
    assert cypher_evidence["agentic_cypher_plan_example"]["validation"]["valid"] is True
    assert cypher_evidence["agentic_cypher_plan_example"]["validation"]["read_only"] is True
    assert matrix["ai_rag"]["neo4j_payload_export"]["status"] == "ready"
    assert matrix["ai_rag"]["neo4j_payload_export"]["evidence"]["payload_export_ready"] is True
    assert matrix["ai_rag"]["neo4j_payload_export"]["evidence"]["payload_format"] == "neo4j_cypher_v1"
    assert matrix["ai_rag"]["neo4j_payload_export"]["evidence"]["payload_node_count"] >= 1
    assert matrix["ai_rag"]["neo4j_payload_export"]["evidence"]["payload_statement_count"] >= 1
    assert matrix["ai_rag"]["neo4j_import"]["status"] == "degraded"
    assert matrix["ai_rag"]["neo4j_import"]["evidence"]["payload_export_ready"] is True
    assert matrix["ai_rag"]["neo4j_import"]["evidence"]["fallback_reason"] == "missing_settings:neo4j_uri"
    live_cypher = matrix["ai_rag"]["graphrag_live_cypher_query"]
    assert live_cypher["status"] == "degraded"
    assert live_cypher["evidence"]["endpoint"] == "GET /supply-chain/graph/cypher-query"
    assert live_cypher["evidence"]["neo4j_ready"] is False
    assert live_cypher["evidence"]["planner_enabled"] is True


def test_rag_settings_defaults(monkeypatch) -> None:
    for key in (
        "RAG_EMBEDDING_PROVIDER",
        "RAG_EMBEDDING_MODEL",
        "RAG_EMBEDDING_OUTPUT_DIMENSIONALITY",
        "RAG_ALLOW_CHROMA_DEFAULT_EMBEDDING_FALLBACK",
        "RAG_HYBRID_SEARCH_ENABLED",
        "RAG_VECTOR_WEIGHT",
        "RAG_KEYWORD_WEIGHT",
        "RAG_RERANK_TOP_K",
        "RAG_CHROMA_QUERY_TIMEOUT_SECONDS",
        "RAG_CHROMA_GET_TIMEOUT_SECONDS",
        "RAG_CHROMA_UPSERT_TIMEOUT_SECONDS",
        "RAG_RERANKER_PROVIDER",
        "RAG_RERANKER_MODEL",
        "RAG_RERANKER_TEXT_LIMIT",
        "RAG_RERANKER_TIMEOUT_SECONDS",
        "RAG_LLM_RERANKER_ENABLED",
        "RAG_LLM_RERANKER_MAX_DOCUMENTS",
        "CHROMA_API_URL",
        "CHROMA_TENANT",
        "CHROMA_DATABASE",
        "COHERE_API_KEY",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "NEO4J_TIMEOUT_SECONDS",
        "NEO4J_STATUS_CHECK_CONNECTION",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)

    assert settings.rag_embedding_provider == "google_genai"
    assert settings.rag_embedding_model == "gemini-embedding-2"
    assert settings.rag_embedding_output_dimensionality is None
    assert settings.rag_index_schema_version == "identity-v2"
    assert settings.rag_allow_chroma_default_embedding_fallback is False
    assert settings.rag_hybrid_search_enabled is True
    assert settings.rag_vector_weight == 0.60
    assert settings.rag_keyword_weight == 0.40
    assert settings.rag_rerank_top_k == 40
    assert settings.rag_chroma_query_timeout_seconds == 12.0
    assert settings.rag_chroma_get_timeout_seconds == 8.0
    assert settings.rag_chroma_upsert_timeout_seconds == 30.0
    assert settings.rag_reranker_provider == "auto"
    assert settings.rag_reranker_model == "BAAI/bge-reranker-v2-m3"
    assert settings.rag_reranker_text_limit == 4000
    assert settings.rag_reranker_timeout_seconds == 15.0
    assert settings.rag_llm_reranker_enabled is True
    assert settings.rag_llm_reranker_max_documents == 8
    assert settings.chroma_api_url == ""
    assert settings.chroma_tenant == "default_tenant"
    assert settings.chroma_database == "default_database"
    assert settings.cohere_api_key is None
    assert settings.neo4j_uri == ""
    assert settings.neo4j_user == ""
    assert settings.neo4j_password is None
    assert settings.neo4j_database == ""
    assert settings.neo4j_timeout_seconds == 15.0
    assert settings.neo4j_status_check_connection is True


def test_neo4j_import_capability_status_distinguishes_connection_failure() -> None:
    assert _neo4j_import_capability_status({"ready": True, "configured": True}) == "ready"
    assert _neo4j_import_capability_status({"ready": False, "configured": False}) == "not_configured"
    assert (
        _neo4j_import_capability_status(
            {"ready": False, "configured": False, "payload_export_ready": True}
        )
        == "degraded"
    )
    assert (
        _neo4j_import_capability_status(
            {"ready": False, "configured": True, "fallback_reason": "connection_failed:neo4j"}
        )
        == "degraded"
    )
