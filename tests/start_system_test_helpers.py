from __future__ import annotations


def ready_upgrade_matrix(overrides: dict | None = None) -> dict:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "llm_quota_routing": {"status": "ready", "evidence": {}},
            "hybrid_search": {"status": "ready", "evidence": {}},
            "reranking": {"status": "ready", "evidence": {}},
            "llm_observability": {"status": "ready", "evidence": {}},
            "visual_rag": {"status": "ready", "evidence": {}},
            "graphrag_context": {"status": "ready", "evidence": {}},
            "graphrag_path_reasoning": {"status": "ready", "evidence": {}},
            "graphrag_agentic_cypher": {"status": "ready", "evidence": {}},
            "neo4j_payload_export": {"status": "ready", "evidence": {}},
            "neo4j_import": {"status": "ready", "evidence": {}},
            "graphrag_live_cypher_query": {"status": "ready", "evidence": {}},
        },
        "architecture": {
            "thin_api_controller": {"status": "ready", "evidence": {}},
            "workflow_orchestration": {"status": "ready", "evidence": {}},
            "streamlit_mpa_background_tasks": {"status": "ready", "evidence": {}},
            "background_task_queue": {"status": "ready", "evidence": {}},
            "python_runtime": {"status": "ready", "evidence": {}},
            "database_migrations": {"status": "ready", "evidence": {"up_to_date": True}},
            "secret_scanning": {"status": "ready", "evidence": {}},
        },
        "data_business_logic": {
            "market_data_cache": {"status": "ready", "evidence": {}},
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
            "latest_report_retention": {"status": "ready", "evidence": {}},
            "company_filing_fetch_hardening": {"status": "ready", "evidence": {}},
            "company_filing_render_provider_contract": {"status": "ready", "evidence": {}},
            "company_filing_pdf_table_parser_runtime": {"status": "ready", "evidence": {}},
            "company_filing_browser_or_proxy_fallback": {"status": "ready", "evidence": {}},
            "company_filing_structured_api_fallback": {"status": "ready", "evidence": {}},
            "company_filing_structured_api_sample_contract": {"status": "ready", "evidence": {}},
            "company_filing_cache": {"status": "ready", "evidence": {}},
            "source_quality_weighting": {"status": "ready", "evidence": {}},
        },
    }
    for path, value in (overrides or {}).items():
        area, capability = path.split(".")
        matrix[area][capability] = value
    return matrix
