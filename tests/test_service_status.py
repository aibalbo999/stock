import sys
from pathlib import Path

from app.core.config import Settings
from app.data_sources.company_filings import COMPANY_FILING_RETRYABLE_HTTP_STATUSES
from app.data_sources.market import FUGLE_RETRYABLE_HTTP_STATUSES, FINMIND_RETRYABLE_HTTP_STATUSES
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD
from app.services.service_status import (
    _redact_url,
    service_status,
)
from app.services.status_company_filings import (
    _company_filing_pdf_parser_status,
    _company_filing_user_agent_status,
)
from app.services.status_graphrag import _neo4j_import_capability_status
from app.services.status_market_data import _market_data_provider_readiness


def test_redact_url_with_password() -> None:
    assert _redact_url("redis://user:secret@localhost:6379/0") == "redis://user:***@localhost:6379/0"


def test_service_status_shape() -> None:
    status = service_status()
    service_status_source = Path("app/services/service_status.py").read_text()
    status_graphrag_source = Path("app/services/status_graphrag.py").read_text()
    status_market_data_source = Path("app/services/status_market_data.py").read_text()
    status_vector_store_source = Path("app/services/status_vector_store.py").read_text()
    status_python_runtime_source = Path("app/services/status_python_runtime.py").read_text()
    status_security_source = Path("app/services/status_security.py").read_text()
    status_task_queue_source = Path("app/services/status_task_queue.py").read_text()
    status_company_filings_source = Path("app/services/status_company_filings.py").read_text()

    assert "database" in status
    assert "redis" in status
    assert "gemini" in status
    assert "finmind" in status
    assert "fugle" in status
    assert "market_data_cache" in status
    assert "company_filings" in status
    assert "vector_store" in status
    assert "supply_chain_graph" in status
    assert "workflow_orchestration" in status
    assert "python_runtime" in status
    assert "task_queue" in status
    assert status["market_data_cache"]["enabled"] is True
    assert status["market_data_cache"]["available"] == bool(status["redis"]["ok"])
    assert status["market_data_cache"]["stale_rescue_enabled"] is True
    assert status["market_data_cache"]["stale_source_marker"] == "cached-stale"
    assert status["market_data_cache"]["latest_only_source_marker"] == "latest-only"
    assert status["market_data_cache"]["price_provider_order"] == ["finmind", "fugle"]
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["live_providers"] == [
        "finmind",
        "fugle",
        "twse_tpex_openapi_latest",
    ]
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["fallback_enabled"] is True
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["fugle_fallback_endpoints"] == [
        "historical/candles",
        "historical/stats",
    ]
    assert status["market_data_cache"]["provider_matrix"]["price_history"]["official_openapi_latest_snapshot_fallback"] is True
    assert status["market_data_cache"]["provider_matrix"]["monthly_revenue"]["live_providers"] == [
        "finmind",
        "twse_tpex_openapi_latest",
    ]
    assert status["market_data_cache"]["provider_matrix"]["monthly_revenue"]["fallback_enabled"] is True
    assert status["market_data_cache"]["provider_matrix"]["financial_metrics"]["fallback_enabled"] is True
    assert (
        status["market_data_cache"]["provider_matrix"]["financial_metrics"]["official_openapi_scope"]
        == "latest_quarter_income_balance_only"
    )
    assert (
        status["market_data_cache"]["provider_matrix"]["valuation"]["redis_cache_ttl_seconds"]
        == Settings().valuation_metrics_cache_ttl_seconds
    )
    assert "TaiwanStockPER" in status["market_data_cache"]["datasets"]
    assert status["market_data_cache"]["price_history_ttl_seconds"] == Settings().price_history_cache_ttl_seconds
    assert status["market_data_cache"]["monthly_revenue_ttl_seconds"] == Settings().monthly_revenue_cache_ttl_seconds
    assert status["market_data_cache"]["financial_metrics_ttl_seconds"] == Settings().financial_metrics_cache_ttl_seconds
    assert status["market_data_cache"]["valuation_metrics_ttl_seconds"] == Settings().valuation_metrics_cache_ttl_seconds
    assert status["market_data_cache"]["official_openapi_fallback_enabled"] is True
    assert status["market_data_cache"]["official_openapi_timeout_seconds"] == 15.0
    assert status["finmind"]["collector_path"] == "app/services/status_market_data.py"
    assert status["fugle"]["collector_path"] == "app/services/status_market_data.py"
    assert status["market_data_cache"]["collector_path"] == "app/services/status_market_data.py"
    assert "from app.services.status_market_data import (" in service_status_source
    assert "def _market_data_provider_matrix(" not in service_status_source
    assert "def market_data_status(" in status_market_data_source
    assert status["company_filings"]["http_retries"] == Settings().company_filing_http_retries
    assert status["company_filings"]["collector_path"] == "app/services/status_company_filings.py"
    assert "from app.services.status_company_filings import (" in service_status_source
    assert "def _company_filing_pdf_parser_status(" not in service_status_source
    assert "def company_filing_status(" in status_company_filings_source
    assert status["company_filings"]["retryable_http_statuses"] == sorted(COMPANY_FILING_RETRYABLE_HTTP_STATUSES)
    assert (
        status["company_filings"]["base_retry_delay_seconds"]
        == Settings().company_filing_base_retry_delay_seconds
    )
    assert (
        status["company_filings"]["max_retry_delay_seconds"]
        == Settings().company_filing_max_retry_delay_seconds
    )
    assert status["company_filings"]["pdf_parser"] == Settings().company_filing_pdf_parser
    assert status["company_filings"]["pdf_extract_tables"] is True
    assert "pdfplumber_available" in status["company_filings"]["pdf_parser_dependencies"]
    assert "unstructured_pdf_available" in status["company_filings"]["pdf_parser_dependencies"]
    assert status["company_filings"]["pdf_parser_available"] is status["company_filings"][
        "pdf_parser_dependencies"
    ]["configured_parser_available"]
    assert status["company_filings"]["pdf_table_parser_available"] is status["company_filings"][
        "pdf_parser_dependencies"
    ]["table_parser_available"]
    assert status["company_filings"]["html_extract_tables"] is True
    assert status["company_filings"]["cache_enabled"] is True
    assert status["company_filings"]["cache_available"] == bool(status["redis"]["ok"])
    assert status["company_filings"]["cache_backend"] == "redis"
    assert status["company_filings"]["cache_key_namespace"] == "stock-ai:company-filing:url-document:v1"
    assert status["company_filings"]["cache_key_scope"] == [
        "url",
        "parser",
        "extract_tables",
        "html_extract_tables",
    ]
    assert status["company_filings"]["cache_ttl_seconds"] == Settings().company_filing_cache_ttl_seconds
    assert status["company_filings"]["browser_render_enabled"] is False
    assert status["company_filings"]["browser_render_provider"] == "browserless"
    assert "flaresolverr" in status["company_filings"]["browser_render_supported_providers"]
    assert status["company_filings"]["browser_render_configured"] is False
    assert status["company_filings"]["browser_render_endpoint_reachable"] is False
    assert "fallback_reason" in status["company_filings"]["browser_render_runtime"]
    assert status["company_filings"]["browser_render_runtime"]["smoke_cli"].endswith(
        "scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    )
    assert status["company_filings"]["browser_render_timeout_seconds"] == 30.0
    assert status["company_filings"]["structured_api_configured"] is False
    assert status["company_filings"]["structured_api_provider"] is None
    assert status["company_filings"]["structured_api_url_configured"] is False
    assert status["company_filings"]["structured_api_token_configured"] is False
    assert status["company_filings"]["visual_rag_enabled"] is Settings().company_filing_visual_rag_enabled
    assert status["company_filings"]["visual_rag_mode"] == Settings().company_filing_visual_rag_mode
    assert isinstance(status["company_filings"]["visual_rag_runtime_available"], bool)
    assert status["company_filings"]["visual_rag_model"] == Settings().company_filing_visual_rag_model
    assert status["company_filings"]["visual_rag_max_pages"] == Settings().company_filing_visual_rag_max_pages
    assert status["company_filings"]["visual_rag_dpi"] == 144
    assert "fallback_reason" in status["company_filings"]["visual_rag_runtime"]
    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_configured"] is bool(
        status["company_filings"]["playwright_render_browser_available"]
    )
    assert isinstance(status["company_filings"]["playwright_render_dependency_available"], bool)
    assert isinstance(status["company_filings"]["playwright_render_browser_available"], bool)
    assert "fallback_reason" in status["company_filings"]["playwright_render_runtime"]
    assert status["company_filings"]["playwright_render_runtime"]["smoke_cli"].endswith(
        "scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    )
    assert status["company_filings"]["playwright_render_browser"] == "chromium"
    assert status["company_filings"]["playwright_render_wait_until"] == "networkidle"
    assert status["company_filings"]["playwright_render_timeout_seconds"] == 30.0
    assert status["company_filings"]["custom_user_agent_count"] == 0
    assert status["company_filings"]["default_user_agent_count"] >= 1
    assert status["company_filings"]["effective_user_agent_count"] >= 1
    assert status["company_filings"]["user_agent_mode"] == "default_browser_like"
    assert status["company_filings"]["anti_crawl_identity_enabled"] is True
    assert status["company_filings"]["user_agent_retry_rotation_enabled"] is True
    assert status["company_filings"]["proxy_retry_rotation_enabled"] is False
    assert status["company_filings"]["identity_retry_rotation_enabled"] is True
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is bool(
        status["company_filings"]["browser_render_configured"]
        or status["company_filings"]["playwright_render_configured"]
        or status["company_filings"]["proxy_count"]
    )
    assert status["finmind"]["retryable_http_statuses"] == sorted(FINMIND_RETRYABLE_HTTP_STATUSES)
    assert status["finmind"]["public_fallback_enabled"] is True
    assert status["finmind"]["data_access_ready"] is True
    assert status["finmind"]["mode"] in {"authenticated", "public_limited"}
    assert status["finmind"]["max_retries"] == Settings().finmind_max_retries
    assert status["finmind"]["base_retry_delay_seconds"] == Settings().finmind_base_retry_delay_seconds
    assert status["finmind"]["max_retry_delay_seconds"] == Settings().finmind_max_retry_delay_seconds
    assert status["finmind"]["timeout_seconds"] == Settings().finmind_timeout_seconds
    assert status["finmind"]["connect_timeout_seconds"] == Settings().finmind_connect_timeout_seconds
    assert status["finmind"]["concurrency"] == Settings().finmind_concurrency
    assert status["finmind"]["circuit_breaker_enabled"] == Settings().finmind_circuit_breaker_enabled
    assert (
        status["finmind"]["circuit_breaker_failure_threshold"]
        == Settings().finmind_circuit_breaker_failure_threshold
    )
    assert (
        status["finmind"]["circuit_breaker_recovery_seconds"]
        == Settings().finmind_circuit_breaker_recovery_seconds
    )
    assert status["fugle"]["configured"] is False
    assert status["fugle"]["price_history_provider"] is True
    assert status["fugle"]["price_fallback_endpoints"] == ["historical/candles", "historical/stats"]
    assert status["fugle"]["provider_order"] == ["finmind", "fugle"]
    assert status["fugle"]["retryable_http_statuses"] == sorted(FUGLE_RETRYABLE_HTTP_STATUSES)
    assert status["fugle"]["max_retries"] == Settings().fugle_max_retries
    assert status["fugle"]["base_retry_delay_seconds"] == Settings().fugle_base_retry_delay_seconds
    assert status["fugle"]["max_retry_delay_seconds"] == Settings().fugle_max_retry_delay_seconds
    assert status["fugle"]["timeout_seconds"] == Settings().fugle_timeout_seconds
    assert status["fugle"]["connect_timeout_seconds"] == Settings().fugle_connect_timeout_seconds
    assert status["fugle"]["circuit_breaker_enabled"] == Settings().fugle_circuit_breaker_enabled
    assert (
        status["fugle"]["circuit_breaker_failure_threshold"]
        == Settings().fugle_circuit_breaker_failure_threshold
    )
    assert (
        status["fugle"]["circuit_breaker_recovery_seconds"]
        == Settings().fugle_circuit_breaker_recovery_seconds
    )
    assert status["database"]["init_mode"] == Settings().database_init_mode
    assert status["database"]["create_all_non_sqlite_allowed"] is False
    assert "migration" in status["database"]
    assert "up_to_date" in status["database"]["migration"]
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
    assert status["vector_store"]["retrieval_status"]["tokenizer"] == "latin_terms+traditional_chinese_2_4_ngrams"
    assert status["vector_store"]["retrieval_status"]["embedding_identity_header_enabled"] is True
    assert status["vector_store"]["retrieval_status"]["retrieval_trace_enabled"] is True
    assert "final_score" in status["vector_store"]["retrieval_status"]["retrieval_trace_fields"]
    assert "entity_tickers" in status["vector_store"]["retrieval_status"]["keyword_identity_fields"]
    assert "entity_names" in status["vector_store"]["retrieval_status"]["keyword_identity_fields"]
    assert status["vector_store"]["retrieval_status"]["index_schema_version"] == Settings().rag_index_schema_version
    assert "identity_v2" in status["vector_store"]["retrieval_status"]["collection_name_example"]
    assert status["vector_store"]["retrieval_status"]["keyword_corpus_limit"] == Settings().rag_keyword_corpus_limit
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
    assert "from app.services.status_vector_store import vector_store_status as collect_vector_store_status" in (
        service_status_source
    )
    assert "def _vector_store_persistent_collection_enabled(" not in service_status_source
    assert "def vector_store_status(" in status_vector_store_source
    assert status["supply_chain_graph"]["enabled"] is True
    assert status["supply_chain_graph"]["node_count"] >= 1
    assert status["supply_chain_graph"]["edge_confidence"] == "taxonomy"
    assert status["supply_chain_graph"]["query_expansion_enabled"] is True
    assert status["supply_chain_graph"]["retrieval_hints_enabled"] is True
    assert status["supply_chain_graph"]["retrieval_query_plan_enabled"] is True
    assert status["supply_chain_graph"]["retrieval_query_strategy"] == "taxonomy_graph_query_expansion"
    assert "corroborated" in status["supply_chain_graph"]["retrieval_evidence_policy"]
    assert status["supply_chain_graph"]["retrieval_query_example"]
    assert status["supply_chain_graph"]["collector_path"] == "app/services/status_graphrag.py"
    assert "from app.services.status_graphrag import (" in service_status_source
    assert "def _supply_chain_graph_status(" not in service_status_source
    assert "def supply_chain_graph_status(" in status_graphrag_source
    assert status["supply_chain_graph"]["neo4j_export_enabled"] is True
    assert status["supply_chain_graph"]["neo4j_import"]["ready"] is False
    assert status["supply_chain_graph"]["neo4j_import"]["fallback_reason"] == "missing_settings:neo4j_uri"
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
    assert status["supply_chain_graph"]["path_reasoning_strategy"] == "taxonomy_graph_shortest_path_reasoning"
    assert status["supply_chain_graph"]["path_reasoning_endpoint"] == "GET /supply-chain/graph/reasoning"
    assert "shortestPath" in status["supply_chain_graph"]["neo4j_shortest_path_template"]
    assert status["workflow_orchestration"]["engine"] == Settings().workflow_engine
    assert status["workflow_orchestration"]["checkpoint_store"] == "analysis_run.payload_json"
    assert status["workflow_orchestration"]["local_fallback_enabled"] is True
    assert status["workflow_orchestration"]["ready"] is True
    assert status["security_scanning"]["external_engine_integration"] is True
    assert status["security_scanning"]["detect_secrets_dependency_declared"] is True
    assert status["security_scanning"]["local_regex_fallback_enabled"] is True
    assert status["security_scanning"]["collector_path"] == "app/services/status_security.py"
    assert "from app.services.status_security import security_scan_status as collect_security_scan_status" in (
        service_status_source
    )
    assert "def _security_scan_status(" not in service_status_source
    assert "def security_scan_status(" in status_security_source
    assert status["security_scanning"]["default_engine"] in {
        "detect-secrets",
        "gitleaks",
        "local_regex",
    }
    assert status["task_queue"]["collector_path"] == "app/services/status_task_queue.py"
    assert status["task_queue"]["broker_ok"] == status["redis"]["ok"]
    assert status["task_queue"]["backend_ok"] == status["redis"]["ok"]
    assert status["task_queue"]["submission_contract_ready"] is True
    assert status["task_queue"]["processing_ready"] is bool(
        status["task_queue"]["ready"] and status["task_queue"]["worker_online"]
    )
    assert status["task_queue"]["task_export_namespace_available"] is True
    assert status["task_queue"]["celery_app_available"] is True
    assert isinstance(status["task_queue"]["worker_ping_checked"], bool)
    assert isinstance(status["task_queue"]["worker_online"], bool)
    assert isinstance(status["task_queue"]["worker_count"], int)
    assert isinstance(status["task_queue"]["worker_nodes"], list)
    assert status["task_queue"]["worker_ping_timeout_seconds"] >= 0.1
    assert status["task_queue"]["required_task_exports"] == [
        "celery_app",
        "generate_report_task",
        "discovered_report_task",
        "data_operation_task",
        "report_follow_up_task",
    ]
    assert status["task_queue"]["missing_task_exports"] == []
    assert status["task_queue"]["task_names_match_expected"] is True
    assert "POST /tasks/data-operation" in status["task_queue"]["submission_endpoints"]
    assert "GET /tasks/summary" in status["task_queue"]["status_endpoints"]
    assert status["celery"]["ready"] == status["task_queue"]["ready"]
    assert status["celery"]["submission_contract_ready"] is True
    assert "from app.services.status_task_queue import task_queue_status as collect_task_queue_status" in (
        service_status_source
    )
    assert "def task_queue_status(" in status_task_queue_source
    assert status["candidate_confidence"]["high_threshold"] == HIGH_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["medium_threshold"] == MEDIUM_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["source_credibility_weights"]["official"] == 1.0
    assert status["candidate_confidence"]["source_credibility_weights"]["investment_blog"] < 0.75
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
        matrix["ai_rag"]["visual_rag"]["evidence"]["runtime_available"]
        is status["company_filings"]["visual_rag_runtime_available"]
    )
    assert "fallback_reason" in matrix["ai_rag"]["visual_rag"]["evidence"]["runtime"]
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
    assert "shortestPath" in matrix["ai_rag"]["graphrag_path_reasoning"]["evidence"]["neo4j_shortest_path_template"]
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
    assert matrix["architecture"]["thin_api_controller"]["status"] == "ready"
    assert (
        matrix["architecture"]["thin_api_controller"]["evidence"]["collector_path"]
        == "app/services/status_api_architecture.py"
    )
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_py_lines"] <= 120
    assert "report_routes.py" in matrix["architecture"]["thin_api_controller"]["evidence"]["route_modules"]
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["app_factory_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_uses_app_factory"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["compatibility_exports_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_uses_compatibility_exports"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["service_factory_lines"] < 260
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["report_service_factory_extracted"] is True
    assert (
        matrix["architecture"]["thin_api_controller"]["evidence"]["report_service_factory_path"]
        == "app/api/service_factory_report.py"
    )
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["data_service_factory_extracted"] is True
    assert (
        matrix["architecture"]["thin_api_controller"]["evidence"]["data_service_factory_path"]
        == "app/api/service_factory_data.py"
    )
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["workflow_service_factory_extracted"] is True
    assert (
        matrix["architecture"]["thin_api_controller"]["evidence"]["workflow_service_factory_path"]
        == "app/api/service_factory_workflow.py"
    )
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["ai_graph_service_factory_extracted"] is True
    assert (
        matrix["architecture"]["thin_api_controller"]["evidence"]["ai_graph_service_factory_path"]
        == "app/api/service_factory_ai.py"
    )
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["compatibility_helpers_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_uses_compatibility_helpers"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["api_runtime_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_uses_api_runtime"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["task_uses_api_runtime"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["task_exports_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["api_runtime_uses_task_exports"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["task_imports_api_main"] is False
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["compatibility_exports_imports_tasks"] is False
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_direct_domain_import_count"] == 0
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["structured_task_submission_errors"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["task_submission_error_detail_path"] == (
        "app/api/error_details.py"
    )
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["task_submission_error_endpoint_coverage"] == {
        "generate_report_async": True,
        "run_discovered_async": True,
        "data_operation": True,
        "report_follow_up": True,
    }
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["compatibility_service_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_imports_legacy_facade"] is False
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["legacy_facade_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["legacy_facade_alias_only"] is True
    task_queue_arch = matrix["architecture"]["background_task_queue"]
    assert task_queue_arch["status"] == ("ready" if status["task_queue"]["ready"] else "degraded")
    assert task_queue_arch["evidence"]["submission_contract_ready"] is True
    assert task_queue_arch["evidence"]["broker_ok"] == status["redis"]["ok"]
    assert task_queue_arch["evidence"]["processing_ready"] == status["task_queue"]["processing_ready"]
    assert task_queue_arch["evidence"]["worker_online"] == status["task_queue"]["worker_online"]
    assert "worker_nodes" in task_queue_arch["evidence"]
    assert task_queue_arch["evidence"]["structured_task_submission_errors"] is True
    assert task_queue_arch["evidence"]["task_failure_diagnostics_shared_service"] is True
    assert task_queue_arch["evidence"]["task_failure_diagnostics_persisted_to_run_payload"] is True
    assert "POST /tasks/data-operation" in task_queue_arch["evidence"]["submission_endpoints"]
    assert matrix["architecture"]["workflow_orchestration"]["status"] == "ready"
    python_runtime = matrix["architecture"]["python_runtime"]
    expected_python_runtime_status = "ready" if sys.version_info[:2] >= (3, 11) else "degraded"
    assert python_runtime["status"] == expected_python_runtime_status
    assert status["python_runtime"]["required_specifier"] == ">=3.11"
    assert status["python_runtime"]["minimum_supported"] == "3.11"
    assert status["python_runtime"]["python_version_file"] == "3.11"
    assert status["python_runtime"]["project_targets_aligned"] is True
    assert status["python_runtime"]["collector_path"] == "app/services/status_python_runtime.py"
    assert "from app.services.status_python_runtime import (" in service_status_source
    assert "def _python_runtime_status(" not in service_status_source
    assert "def python_runtime_status(" in status_python_runtime_source
    assert (
        status["python_runtime"]["bootstrap_cli"]
        == ".venv/bin/python scripts/bootstrap_python_runtime.py --apply --replace-existing"
    )
    assert status["python_runtime"]["bootstrap_dry_run_cli"].endswith(
        "scripts/bootstrap_python_runtime.py --json"
    )
    assert status["python_runtime"]["interpreter_install_hints"][0] == {
        "tool": "homebrew",
        "command": "brew install python@3.11",
        "venv_command": "python3.11 -m venv .venv",
    }
    assert matrix["architecture"]["database_migrations"]["status"] in {"ready", "degraded"}
    assert matrix["architecture"]["database_migrations"]["evidence"]["head_revision"]
    assert matrix["architecture"]["secret_scanning"]["status"] == "ready"
    assert (
        matrix["architecture"]["secret_scanning"]["evidence"]["local_regex_fallback_role"]
        == "fallback_only"
    )
    assert "detect-secrets" in matrix["architecture"]["secret_scanning"]["evidence"][
        "supported_external_engines"
    ]
def test_settings_default_api_base_url() -> None:
    assert Settings().api_base_url == "http://127.0.0.1:8000"


def test_database_init_mode_default_uses_deployment_migrations() -> None:
    assert Settings().database_init_mode == "alembic"
    assert Settings().database_allow_create_all_non_sqlite is False


def test_candidate_confidence_threshold_settings_defaults() -> None:
    settings = Settings()

    assert settings.candidate_confidence_high_threshold == HIGH_CONFIDENCE_THRESHOLD
    assert settings.candidate_confidence_medium_threshold == MEDIUM_CONFIDENCE_THRESHOLD


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


def test_company_filing_user_agent_status_uses_default_browser_like_agents() -> None:
    status = _company_filing_user_agent_status("")

    assert status["custom_user_agent_count"] == 0
    assert status["default_user_agent_count"] >= 1
    assert status["effective_user_agent_count"] == status["default_user_agent_count"]
    assert status["user_agent_mode"] == "default_browser_like"
    assert status["anti_crawl_identity_enabled"] is True


def test_company_filing_pdf_parser_status_requires_table_capable_dependency() -> None:
    def fake_module_available(name: str) -> bool:
        return name == "pypdf"

    status = _company_filing_pdf_parser_status(
        "auto",
        extract_tables=True,
        module_available=fake_module_available,
    )

    assert status["configured_parser_available"] is True
    assert status["resolved_parser_candidates"] == ["pypdf"]
    assert status["table_parser_available"] is False
    assert status["table_extraction_runtime_available"] is False
    assert status["fallback_reason"] == "missing_table_pdf_parser_dependency:pdfplumber_or_unstructured"


def test_company_filing_pdf_parser_status_accepts_pdfplumber_for_tables() -> None:
    def fake_module_available(name: str) -> bool:
        return name == "pdfplumber"

    status = _company_filing_pdf_parser_status(
        "auto",
        extract_tables=True,
        module_available=fake_module_available,
    )

    assert status["configured_parser_available"] is True
    assert status["resolved_parser_candidates"] == ["pdfplumber"]
    assert status["table_parser_available"] is True
    assert status["table_extraction_runtime_available"] is True
    assert status["fallback_reason"] is None


def test_company_filing_user_agent_status_counts_custom_agents() -> None:
    status = _company_filing_user_agent_status("UA-A,UA-B")

    assert status["custom_user_agent_count"] == 2
    assert status["effective_user_agent_count"] == 2
    assert status["user_agent_mode"] == "custom"
    assert status["anti_crawl_identity_enabled"] is True


def test_market_data_provider_readiness_distinguishes_public_finmind_and_rescue_sources() -> None:
    degraded = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"]},
        {"configured": False, "public_fallback_enabled": False, "data_access_ready": False},
        {"configured": False},
    )

    assert degraded["ready"] is False
    assert degraded["finmind_authenticated"] is False
    assert degraded["finmind_public_fallback_enabled"] is False
    assert degraded["finmind_data_access_ready"] is False
    assert degraded["fugle_price_fallback_configured"] is False
    assert degraded["official_openapi_fallback_enabled"] is False
    assert degraded["official_openapi_fallback_scope"] == []
    assert "missing_finmind_access" in degraded["fallback_reason"]
    assert "missing_price_rescue_provider" in degraded["fallback_reason"]

    ready = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"]},
        {"configured": True, "public_fallback_enabled": False, "data_access_ready": True},
        {"configured": True},
    )

    assert ready["ready"] is True
    assert ready["fallback_reason"] is None

    official = _market_data_provider_readiness(
        {"price_provider_order": ["finmind", "fugle"], "official_openapi_fallback_enabled": True},
        {"configured": False, "public_fallback_enabled": True, "data_access_ready": True},
        {"configured": False},
    )

    assert official["ready"] is True
    assert official["finmind_access_mode"] == "public_limited"
    assert official["official_openapi_fallback_enabled"] is True
    assert "latest_quarter_income_balance" in official["official_openapi_fallback_scope"]
    assert "finmind_public_limited_mode_for_history_datasets" in official["warnings"]
    assert "missing_fugle_api_key_for_price_fallback" in official["warnings"]


def test_market_data_cache_settings_defaults() -> None:
    settings = Settings()

    assert settings.market_data_cache_enabled is True
    assert settings.market_price_provider_order == "finmind,fugle"
    assert settings.finmind_public_fallback_enabled is True
    assert settings.price_history_cache_ttl_seconds == 24 * 60 * 60
    assert settings.monthly_revenue_cache_ttl_seconds == 7 * 24 * 60 * 60
    assert settings.financial_metrics_cache_ttl_seconds == 31 * 24 * 60 * 60
    assert settings.valuation_metrics_cache_ttl_seconds == 24 * 60 * 60
    assert settings.finmind_max_retries == 2
    assert settings.finmind_base_retry_delay_seconds == 0.5
    assert settings.finmind_max_retry_delay_seconds == 5.0
    assert settings.finmind_timeout_seconds == 20.0
    assert settings.finmind_connect_timeout_seconds == 8.0
    assert settings.finmind_concurrency == 5
    assert settings.finmind_circuit_breaker_enabled is True
    assert settings.finmind_circuit_breaker_failure_threshold == 5
    assert settings.finmind_circuit_breaker_recovery_seconds == 60.0
    assert settings.fugle_max_retries == 2
    assert settings.fugle_base_retry_delay_seconds == 0.5
    assert settings.fugle_max_retry_delay_seconds == 5.0
    assert settings.fugle_timeout_seconds == 20.0
    assert settings.fugle_connect_timeout_seconds == 8.0
    assert settings.fugle_circuit_breaker_enabled is True
    assert settings.fugle_circuit_breaker_failure_threshold == 5
    assert settings.fugle_circuit_breaker_recovery_seconds == 60.0
    assert settings.market_official_openapi_fallback_enabled is True
    assert settings.market_official_openapi_timeout_seconds == 15.0


def test_company_filing_fetch_settings_defaults() -> None:
    settings = Settings()

    assert settings.company_filing_user_agents == ""
    assert settings.company_filing_proxy_urls == ""
    assert settings.company_filing_http_retries == 1
    assert settings.company_filing_base_retry_delay_seconds == 0.5
    assert settings.company_filing_max_retry_delay_seconds == 5.0
    assert settings.company_filing_pdf_parser == "auto"
    assert settings.company_filing_pdf_extract_tables is True
    assert settings.company_filing_html_extract_tables is True
    assert settings.company_filing_cache_enabled is True
    assert settings.company_filing_cache_ttl_seconds == 7 * 24 * 60 * 60
    assert settings.company_filing_browser_render_enabled is False
    assert settings.company_filing_browser_render_provider == "browserless"
    assert settings.company_filing_browser_render_url == ""
    assert settings.company_filing_browser_render_token == ""
    assert settings.company_filing_browser_render_timeout_seconds == 30.0
    assert settings.company_filing_browser_render_concurrency == 4
    assert settings.company_filing_playwright_render_enabled is True
    assert settings.company_filing_playwright_browser == "chromium"
    assert settings.company_filing_playwright_wait_until == "networkidle"
    assert settings.company_filing_playwright_timeout_seconds == 30.0
    assert settings.company_filing_structured_api_provider == ""
    assert settings.company_filing_structured_api_url == ""
    assert settings.company_filing_structured_api_token == ""
    assert settings.company_filing_structured_api_timeout_seconds == 20.0


def test_workflow_orchestration_settings_defaults() -> None:
    settings = Settings()

    assert settings.workflow_engine == "local"
    assert settings.workflow_local_fallback_enabled is True
    assert settings.prefect_api_url == ""
    assert settings.temporal_address == "localhost:7233"
    assert settings.temporal_namespace == "default"
    assert settings.temporal_task_queue == "stock-analysis"
    assert settings.temporal_workflow_name == "StockAnalysisPipeline"
    assert settings.temporal_ui_url == ""
    assert settings.temporal_timeout_seconds == 15.0
    assert settings.airflow_api_url == ""
    assert settings.airflow_dag_id == "stock_analysis_pipeline"
    assert settings.airflow_api_token is None
    assert settings.airflow_username == ""
    assert settings.airflow_password is None
    assert settings.airflow_timeout_seconds == 15.0
