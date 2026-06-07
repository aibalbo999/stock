import sys
from pathlib import Path

from app.core.config import Settings, get_settings
from app.data_sources.company_filings import COMPANY_FILING_RETRYABLE_HTTP_STATUSES
from app.data_sources.market import FUGLE_RETRYABLE_HTTP_STATUSES, FINMIND_RETRYABLE_HTTP_STATUSES
from app.services.candidate_confidence import HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD
from app.services.llm_client import DEFAULT_MAX_RETRIES_PER_KEY, RETRYABLE_HTTP_STATUSES
from app.services.service_status import (
    _redact_url,
    service_status,
)
from app.services.status_company_filings import (
    _company_filing_pdf_parser_status,
    _company_filing_user_agent_status,
)
from app.services.status_frontend import frontend_status
from app.services.status_graphrag import _neo4j_import_capability_status
from app.services.status_llm import (
    _llm_fallback_readiness,
    _llm_model_provider,
    _llm_quota_routing_status,
)
from app.services.status_market_data import _market_data_provider_readiness


def test_redact_url_with_password() -> None:
    assert _redact_url("redis://user:secret@localhost:6379/0") == "redis://user:***@localhost:6379/0"


def test_service_status_shape() -> None:
    status = service_status()
    service_status_source = Path("app/services/service_status.py").read_text()
    status_capability_matrix_source = Path("app/services/status_capability_matrix.py").read_text()
    status_frontend_source = Path("app/services/status_frontend.py").read_text()
    status_llm_source = Path("app/services/status_llm.py").read_text()
    status_graphrag_source = Path("app/services/status_graphrag.py").read_text()
    status_market_data_source = Path("app/services/status_market_data.py").read_text()
    status_vector_store_source = Path("app/services/status_vector_store.py").read_text()
    status_python_runtime_source = Path("app/services/status_python_runtime.py").read_text()
    status_report_retention_source = Path("app/services/status_report_retention.py").read_text()
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
    assert status["gemini"]["retryable_http_statuses"] == sorted(RETRYABLE_HTTP_STATUSES)
    assert status["gemini"]["max_retries_per_key"] == DEFAULT_MAX_RETRIES_PER_KEY
    assert status["gemini"]["base_retry_delay_seconds"] == 0.5
    assert status["gemini"]["max_retry_delay_seconds"] == 5.0
    assert status["gemini"]["provider_keys_configured"]["anthropic"] is False
    assert status["llm_quota_routing"]["ready"] is True
    assert status["llm_quota_routing"]["collector_path"] == "app/services/status_llm.py"
    assert "from app.services.status_llm import (" in service_status_source
    assert "def _llm_quota_routing_status(" not in service_status_source
    assert "def _llm_quota_routing_status(" in status_llm_source
    assert status["llm_quota_routing"]["strategy"] == "smartest_first_then_budget_degrade"
    assert status["llm_quota_routing"]["model_order"][:4] == [
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
    ]
    assert status["llm_quota_routing"]["same_tier_flash_request_budgets"] == {
        "gemini-3.5-flash": 250,
        "gemini-2.5-flash": 250,
        "gemini-3.1-flash-lite": 250,
        "gemini-2.5-flash-lite": 250,
    }
    assert status["llm_quota_routing"]["high_quota_fallback_request_budget"] == 14400
    assert status["llm_quota_routing"]["readiness_checks"]["hard_routing_enabled"] is True
    assert status["llm_quota_routing"]["excluded_media_live_models"] == []
    assert status["llm_observability"]["enabled"] is True
    assert status["llm_observability"]["local_trace_enabled"] is True
    assert "latency_ms" in status["llm_observability"]["captured_fields"]
    assert "total_token_estimate" in status["llm_observability"]["captured_fields"]
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
    assert status["frontend"]["streamlit_entry_uses_navigation"] is True
    assert status["frontend"]["collector_path"] == "app/services/status_frontend.py"
    assert frontend_status()["collector_path"] == "app/services/status_frontend.py"
    assert "from app.services.status_frontend import frontend_status as collect_frontend_status" in service_status_source
    assert "def _frontend_status(" not in service_status_source
    assert "def frontend_status(" in status_frontend_source
    assert status["frontend"]["page_count"] >= 4
    assert status["frontend"]["expected_pages_present"] is True
    assert status["frontend"]["report_html_renderer_extracted"] is True
    assert status["frontend"]["report_html_renderer_path"] == "app/ui/report_html.py"
    assert status["frontend"]["ui_status_helpers_extracted"] is True
    assert status["frontend"]["ui_status_helper_paths"] == [
        "app/ui/follow_up_status.py",
        "app/ui/maintenance_status.py",
    ]
    assert status["frontend"]["ui_api_client_extracted"] is True
    assert status["frontend"]["ui_api_client_path"] == "app/ui/api_client.py"
    assert status["frontend"]["ui_background_task_client_extracted"] is True
    assert status["frontend"]["ui_background_task_client_path"] == "app/ui/background_tasks.py"
    assert status["frontend"]["ui_task_queue_preflight_enabled"] is True
    assert status["frontend"]["ui_task_queue_preflight_degrades_open"] is True
    assert status["frontend"]["ui_task_queue_worker_warning_enabled"] is True
    assert status["frontend"]["ui_task_queue_health_panel_extracted"] is True
    assert status["frontend"]["ui_task_failure_drilldown_enabled"] is True
    assert status["frontend"]["ui_task_failure_category_display_enabled"] is True
    assert status["frontend"]["ui_task_failure_trend_enabled"] is True
    assert status["frontend"]["ui_task_failure_alerts_enabled"] is True
    assert status["frontend"]["ui_task_status_panel_extracted"] is True
    assert status["frontend"]["ui_task_status_failure_diagnostics_enabled"] is True
    assert status["frontend"]["ui_task_status_panel_path"] == "app/ui/task_status_panel.py"
    assert status["frontend"]["task_retry_uses_scoped_state_key"] is True
    assert status["frontend"]["ui_report_state_extracted"] is True
    assert status["frontend"]["ui_report_state_path"] == "app/ui/report_state.py"
    assert status["frontend"]["ui_report_panels_extracted"] is True
    assert status["frontend"]["ui_report_panels_path"] == "app/ui/report_panels.py"
    assert status["frontend"]["ui_report_follow_up_controls_extracted"] is True
    assert status["frontend"]["ui_report_follow_up_controls_path"] == "app/ui/report_follow_up_controls.py"
    assert status["frontend"]["ui_report_markdown_helpers_extracted"] is True
    assert status["frontend"]["ui_report_markdown_helpers_path"] == "app/ui/report_markdown.py"
    assert status["frontend"]["ui_report_candidate_audit_extracted"] is True
    assert status["frontend"]["ui_report_candidate_audit_path"] == "app/ui/report_candidate_audit.py"
    assert status["frontend"]["ui_report_formatters_extracted"] is True
    assert status["frontend"]["ui_report_formatters_path"] == "app/ui/report_formatters.py"
    assert status["frontend"]["ui_report_sections_extracted"] is True
    assert status["frontend"]["ui_report_sections_path"] == "app/ui/report_sections.py"
    assert status["frontend"]["ui_wildcard_imports_removed"] is True
    assert status["frontend"]["dashboard_core_lines"] < 1500
    assert status["frontend"]["external_css_loaded"] is True
    assert status["frontend"]["external_report_css_loaded"] is True
    assert status["frontend"]["external_report_css_path"] == "app/ui/styles/report_html.css"
    assert status["frontend"]["uses_task_enqueue_helper"] is True
    assert status["frontend"]["uses_background_task_submit_helper"] is True
    assert status["frontend"]["uses_task_queue_preflight"] is True
    assert status["frontend"]["uses_task_status_panel"] is True
    assert status["frontend"]["asyncio_run_count"] == 0
    assert status["frontend"]["long_blocking_post_timeout_present"] is False
    assert status["frontend"]["sync_report_generate_used"] is False
    assert status["frontend"]["api_task_queue_timeout_seconds"] == 20
    assert status["candidate_confidence"]["high_threshold"] == HIGH_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["medium_threshold"] == MEDIUM_CONFIDENCE_THRESHOLD
    assert status["candidate_confidence"]["source_credibility_weights"]["official"] == 1.0
    assert status["candidate_confidence"]["source_credibility_weights"]["investment_blog"] < 0.75
    matrix = status["upgrade_capability_matrix"]
    assert "from app.services.status_capability_matrix import (" in service_status_source
    assert "build_upgrade_capability_matrix(status)" in service_status_source
    assert "def _upgrade_capability_matrix(" not in service_status_source
    assert "def _api_controller_status(" not in service_status_source
    assert "def upgrade_capability_matrix(" in status_capability_matrix_source
    assert "def _api_controller_status(" in status_capability_matrix_source
    llm_matrix = matrix["ai_rag"]["llm_sdk_and_fallback"]
    llm_evidence = llm_matrix["evidence"]
    assert "sdk_ready" in llm_evidence
    assert "fallback_model_ready_count" in llm_evidence
    if llm_evidence["fallback_model_count"] == 0:
        assert llm_matrix["status"] == "degraded"
    else:
        expected_llm_status = (
            "ready"
            if llm_evidence["sdk_ready"] and llm_evidence["fallback_model_ready_count"] > 0
            else "degraded"
        )
        assert llm_matrix["status"] == expected_llm_status
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
    assert matrix["ai_rag"]["llm_observability"]["status"] == "ready"
    assert matrix["ai_rag"]["llm_observability"]["evidence"]["local_trace_enabled"] is True
    assert "latency_ms" in matrix["ai_rag"]["llm_observability"]["evidence"]["captured_fields"]
    assert "total_token_estimate" in matrix["ai_rag"]["llm_observability"]["evidence"]["captured_fields"]
    quota_routing = matrix["ai_rag"]["llm_quota_routing"]
    assert quota_routing["status"] == "ready"
    assert quota_routing["evidence"]["readiness_checks"]["flash_models_share_request_budget"] is True
    assert (
        quota_routing["evidence"]["readiness_checks"]["high_quota_fallback_after_smart_models"]
        is True
    )
    assert quota_routing["evidence"]["readiness_checks"]["embedding_model_kept_separate"] is True
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
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_py_lines"] <= 120
    assert "report_routes.py" in matrix["architecture"]["thin_api_controller"]["evidence"]["route_modules"]
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["app_factory_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_uses_app_factory"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["compatibility_exports_present"] is True
    assert matrix["architecture"]["thin_api_controller"]["evidence"]["main_uses_compatibility_exports"] is True
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
    frontend_arch = matrix["architecture"]["streamlit_mpa_background_tasks"]
    assert frontend_arch["status"] == "ready"
    assert frontend_arch["evidence"]["streamlit_entry_uses_navigation"] is True
    assert frontend_arch["evidence"]["expected_pages_present"] is True
    assert frontend_arch["evidence"]["report_html_renderer_extracted"] is True
    assert frontend_arch["evidence"]["ui_status_helpers_extracted"] is True
    assert frontend_arch["evidence"]["ui_api_client_extracted"] is True
    assert frontend_arch["evidence"]["ui_background_task_client_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_queue_preflight_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_worker_warning_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_queue_health_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_failure_drilldown_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_category_display_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_trend_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_failure_alerts_enabled"] is True
    assert frontend_arch["evidence"]["ui_task_status_panel_extracted"] is True
    assert frontend_arch["evidence"]["ui_task_status_failure_diagnostics_enabled"] is True
    assert frontend_arch["evidence"]["task_retry_uses_scoped_state_key"] is True
    assert frontend_arch["evidence"]["ui_report_state_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_panels_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_follow_up_controls_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_markdown_helpers_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_candidate_audit_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_formatters_extracted"] is True
    assert frontend_arch["evidence"]["ui_report_sections_extracted"] is True
    assert frontend_arch["evidence"]["ui_wildcard_imports_removed"] is True
    assert frontend_arch["evidence"]["external_report_css_loaded"] is True
    assert frontend_arch["evidence"]["asyncio_run_count"] == 0
    assert frontend_arch["evidence"]["uses_background_task_submit_helper"] is True
    assert frontend_arch["evidence"]["uses_task_queue_preflight"] is True
    assert frontend_arch["evidence"]["long_blocking_post_timeout_present"] is False
    assert frontend_arch["evidence"]["sync_report_generate_used"] is False
    assert all(frontend_arch["evidence"]["async_task_endpoint_coverage"].values())
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
    assert matrix["data_business_logic"]["market_data_cache"]["evidence"]["enabled"] is True
    assert (
        matrix["data_business_logic"]["market_data_cache"]["evidence"]["latest_only_source_marker"]
        == "latest-only"
    )
    market_fallback = matrix["data_business_logic"]["market_data_provider_fallback"]
    market_fallback_evidence = market_fallback["evidence"]
    assert "finmind_authenticated" in market_fallback_evidence
    assert "finmind_public_fallback_enabled" in market_fallback_evidence
    assert market_fallback_evidence["finmind_data_access_ready"] is True
    assert "fugle_price_fallback_configured" in market_fallback_evidence
    assert market_fallback_evidence["official_openapi_fallback_enabled"] is True
    assert "latest_monthly_revenue" in market_fallback_evidence["official_openapi_fallback_scope"]
    assert "five_year_financial_metrics" in market_fallback_evidence["full_history_datasets_requiring_finmind"]
    assert "latest_quarter_income_balance" in market_fallback_evidence["official_openapi_latest_only_datasets"]
    expected_market_status = "ready" if market_fallback_evidence["ready"] else "degraded"
    assert market_fallback["status"] == expected_market_status
    assert (
        status["market_data_cache"]["provider_matrix"]["price_history"]["fallback_configured"]
        is market_fallback_evidence["fugle_price_fallback_configured"]
    )
    report_retention = matrix["data_business_logic"]["latest_report_retention"]
    assert report_retention["status"] == "ready"
    assert status["report_retention"]["policy"] == "latest_per_topic"
    assert status["report_retention"]["collector_path"] == "app/services/status_report_retention.py"
    assert "from app.services.status_report_retention import (" in service_status_source
    assert "def _report_retention_status(" not in service_status_source
    assert "def report_retention_status(" in status_report_retention_source
    assert report_retention["evidence"]["write_prunes_db_by_topic"] is True
    assert report_retention["evidence"]["write_prunes_markdown_by_topic"] is True
    assert report_retention["evidence"]["list_reports_uses_latest_by_topic"] is True
    assert report_retention["evidence"]["quality_summary_uses_latest_by_topic"] is True
    assert report_retention["evidence"]["maintenance_prunes_db_by_topic"] is True
    assert report_retention["evidence"]["maintenance_prunes_markdown_by_topic"] is True
    assert report_retention["evidence"]["run_links_cleared_for_pruned_reports"] is True
    assert matrix["data_business_logic"]["company_filing_fetch_hardening"]["status"] == "ready"
    filing_hardening = matrix["data_business_logic"]["company_filing_fetch_hardening"]["evidence"]
    assert filing_hardening["effective_user_agent_count"] >= 1
    assert filing_hardening["anti_crawl_identity_enabled"] is True
    assert filing_hardening["user_agent_retry_rotation_enabled"] is True
    assert filing_hardening["proxy_retry_rotation_enabled"] is False
    assert filing_hardening["identity_retry_rotation_enabled"] is True
    assert (
        filing_hardening["browser_or_proxy_fallback_configured"]
        is status["company_filings"]["browser_or_proxy_fallback_configured"]
    )
    assert filing_hardening["browser_render_provider"] == "browserless"
    assert filing_hardening["structured_api_configured"] is False
    assert "browser_render_runtime" in filing_hardening
    assert filing_hardening["playwright_render_enabled"] is True
    assert (
        filing_hardening["playwright_render_configured"]
        is status["company_filings"]["playwright_render_configured"]
    )
    assert "playwright_render_runtime" in filing_hardening
    assert "pdf_parser_dependencies" in filing_hardening
    pdf_parser_runtime = matrix["data_business_logic"]["company_filing_pdf_table_parser_runtime"]
    expected_pdf_runtime_status = (
        "ready"
        if (
            not status["company_filings"]["pdf_extract_tables"]
            or status["company_filings"]["pdf_table_extraction_runtime_available"]
        )
        else "not_configured"
    )
    assert pdf_parser_runtime["status"] == expected_pdf_runtime_status
    assert pdf_parser_runtime["evidence"]["pdf_table_parser_available"] is status["company_filings"][
        "pdf_table_parser_available"
    ]
    filing_fallback = matrix["data_business_logic"]["company_filing_browser_or_proxy_fallback"]
    expected_filing_fallback_status = (
        "ready" if status["company_filings"]["browser_or_proxy_fallback_configured"] else "not_configured"
    )
    assert filing_fallback["status"] == expected_filing_fallback_status
    assert (
        filing_fallback["evidence"]["browser_or_proxy_fallback_configured"]
        is status["company_filings"]["browser_or_proxy_fallback_configured"]
    )
    assert filing_fallback["evidence"]["proxy_count"] == 0
    assert filing_fallback["evidence"]["browser_render_configured"] is False
    assert filing_fallback["evidence"]["browser_render_provider"] == "browserless"
    assert "browser_render_runtime" in filing_fallback["evidence"]
    assert (
        filing_fallback["evidence"]["playwright_render_configured"]
        is status["company_filings"]["playwright_render_configured"]
    )
    assert "playwright_render_runtime" in filing_fallback["evidence"]
    structured_api = matrix["data_business_logic"]["company_filing_structured_api_fallback"]
    assert structured_api["status"] == "not_configured"
    assert structured_api["evidence"]["configured"] is False
    assert structured_api["evidence"]["runtime"]["fallback_reason"] == "missing_structured_api_provider_or_url"
    assert matrix["data_business_logic"]["source_quality_weighting"]["status"] == "ready"


def test_settings_default_api_base_url() -> None:
    assert Settings().api_base_url == "http://127.0.0.1:8000"


def test_database_init_mode_default_uses_deployment_migrations() -> None:
    assert Settings().database_init_mode == "alembic"
    assert Settings().database_allow_create_all_non_sqlite is False


def test_candidate_confidence_threshold_settings_defaults() -> None:
    settings = Settings()

    assert settings.candidate_confidence_high_threshold == HIGH_CONFIDENCE_THRESHOLD
    assert settings.candidate_confidence_medium_threshold == MEDIUM_CONFIDENCE_THRESHOLD


def test_llm_retry_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_max_retries_per_key == DEFAULT_MAX_RETRIES_PER_KEY
    assert settings.llm_base_retry_delay_seconds == 0.5
    assert settings.llm_max_retry_delay_seconds == 5.0
    assert settings.primary_llm_model == "gemini-3.5-flash"
    assert settings.local_llm_model == "gemini-2.5-flash-lite"
    assert (
        settings.llm_fallback_models
        == "gemini-2.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemma-4-31b-it"
    )
    assert settings.llm_model_quota_cooldown_seconds == 3600
    assert settings.llm_quota_window_timezone == "America/Los_Angeles"
    assert "gemini-3.5-flash=250" in settings.llm_model_daily_request_budgets
    assert settings.llm_model_cost_rate_card_usd == ""
    assert settings.llm_daily_cost_budget_usd == 0.0
    assert settings.llm_cost_warning_ratio == 0.8
    assert settings.task_observability_stale_minutes == 60


def test_llm_quota_routing_status_requires_smart_first_order_and_equal_budgets() -> None:
    ready = _llm_quota_routing_status(Settings(_env_file=None))

    assert ready["ready"] is True
    assert ready["collector_path"] == "app/services/status_llm.py"
    assert ready["failed_checks"] == []
    assert ready["readiness_checks"]["smart_model_order"] is True
    assert ready["readiness_checks"]["flash_models_share_request_budget"] is True
    assert ready["readiness_checks"]["high_quota_fallback_budget_ready"] is True

    misordered = _llm_quota_routing_status(
        Settings(
            _env_file=None,
            llm_fallback_models=(
                "gemma-4-31b-it,gemini-2.5-flash,"
                "gemini-3.1-flash-lite,gemini-2.5-flash-lite"
            ),
        )
    )
    assert misordered["ready"] is False
    assert "smart_model_order" in misordered["failed_checks"]
    assert "high_quota_fallback_after_smart_models" in misordered["failed_checks"]

    unequal_budget = _llm_quota_routing_status(
        Settings(
            _env_file=None,
            llm_model_daily_request_budgets=(
                "gemini-3.5-flash=250,gemini-2.5-flash=250,"
                "gemini-3.1-flash-lite=100,gemini-2.5-flash-lite=250,"
                "gemma-4-31b-it=14400"
            ),
        )
    )
    assert unequal_budget["ready"] is False
    assert "flash_models_share_request_budget" in unequal_budget["failed_checks"]


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


def test_llm_model_provider_classifies_fallback_models() -> None:
    assert _llm_model_provider("gemini-2.5-flash") == "gemini"
    assert _llm_model_provider("gemini/gemini-2.5-flash") == "gemini"
    assert _llm_model_provider("claude-3-5-haiku") == "anthropic"
    assert _llm_model_provider("anthropic/claude-3-5-haiku") == "anthropic"
    assert _llm_model_provider("gpt-4o-mini") == "openai"
    assert _llm_model_provider("openai/gpt-4o-mini") == "openai"
    assert _llm_model_provider("gemma-4-31b-it") == "gemini"
    assert _llm_model_provider("ollama/gemma3:27b") == "local"
    assert _llm_model_provider("custom/provider") == "unknown"


def test_llm_fallback_readiness_requires_matching_provider_key() -> None:
    rows = _llm_fallback_readiness(
        ["claude-3-5-haiku", "gpt-4o-mini", "gemini/gemini-backup", "gemma-4-31b-it", "custom/provider"],
        {"gemini": True, "openai": False, "anthropic": True, "local": True},
    )

    assert rows == [
        {"model": "claude-3-5-haiku", "provider": "anthropic", "key_configured": True},
        {"model": "gpt-4o-mini", "provider": "openai", "key_configured": False},
        {"model": "gemini/gemini-backup", "provider": "gemini", "key_configured": True},
        {"model": "gemma-4-31b-it", "provider": "gemini", "key_configured": True},
        {"model": "custom/provider", "provider": "unknown", "key_configured": None},
    ]


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


def test_company_filing_playwright_fallback_requires_available_dependency(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_playwright_browser_status",
        lambda browser: {
            "browser": browser,
            "dependency_available": False,
            "browser_available": False,
            "fallback_reason": "missing_dependency:playwright",
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_dependency_available"] is False
    assert status["company_filings"]["playwright_render_browser_available"] is False
    assert status["company_filings"]["playwright_render_configured"] is False
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is False
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "not_configured"


def test_company_filing_playwright_fallback_ready_when_browser_available(monkeypatch) -> None:
    monkeypatch.delenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_playwright_browser_status",
        lambda browser: {
            "browser": browser,
            "dependency_available": True,
            "browser_available": True,
            "browser_executable_exists": True,
            "executable_path": "/tmp/chromium",
            "fallback_reason": None,
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_dependency_available"] is True
    assert status["company_filings"]["playwright_render_browser_available"] is True
    assert status["company_filings"]["playwright_render_configured"] is True
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is True
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "ready"


def test_company_filing_browser_render_fallback_requires_reachable_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "http://127.0.0.1:3000/content")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_browser_render_status",
        lambda: {
            "enabled": True,
            "url_configured": True,
            "endpoint": "http://127.0.0.1:3000/content",
            "connection_checked": True,
            "endpoint_reachable": False,
            "runtime_available": False,
            "fallback_reason": "browser_render_endpoint_unreachable:ConnectionRefusedError",
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["browser_render_enabled"] is True
    assert status["company_filings"]["browser_render_url_configured"] is True
    assert status["company_filings"]["browser_render_endpoint_reachable"] is False
    assert status["company_filings"]["browser_render_configured"] is False
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is False
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "not_configured"
    assert (
        fallback["evidence"]["browser_render_runtime"]["fallback_reason"]
        == "browser_render_endpoint_unreachable:ConnectionRefusedError"
    )


def test_company_filing_browser_render_fallback_ready_when_endpoint_reachable(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "http://127.0.0.1:3000/content")
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_browser_render_status",
        lambda: {
            "enabled": True,
            "url_configured": True,
            "endpoint": "http://127.0.0.1:3000/content",
            "connection_checked": True,
            "endpoint_reachable": True,
            "runtime_available": True,
            "fallback_reason": None,
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["browser_render_enabled"] is True
    assert status["company_filings"]["browser_render_configured"] is True
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is True
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "ready"


def test_company_filing_playwright_fallback_requires_browser_binary(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.service_status.company_filing_playwright_browser_status",
        lambda browser: {
            "browser": browser,
            "dependency_available": True,
            "browser_available": False,
            "browser_executable_exists": False,
            "fallback_reason": f"missing_browser_binary:{browser}; run python -m playwright install {browser}",
        },
    )
    try:
        status = service_status()
    finally:
        get_settings.cache_clear()

    assert status["company_filings"]["playwright_render_enabled"] is True
    assert status["company_filings"]["playwright_render_dependency_available"] is True
    assert status["company_filings"]["playwright_render_browser_available"] is False
    assert status["company_filings"]["playwright_render_configured"] is False
    assert status["company_filings"]["browser_or_proxy_fallback_configured"] is False
    fallback = status["upgrade_capability_matrix"]["data_business_logic"][
        "company_filing_browser_or_proxy_fallback"
    ]
    assert fallback["status"] == "not_configured"
    assert "missing_browser_binary:chromium" in fallback["evidence"]["playwright_render_runtime"][
        "fallback_reason"
    ]


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
