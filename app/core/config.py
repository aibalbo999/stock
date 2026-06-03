from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://stock_ai:stock_ai_password@postgres:5432/stock_ai"
    database_init_mode: str = "alembic"
    database_allow_create_all_non_sqlite: bool = False
    redis_url: str = "redis://localhost:6379/0"
    market_data_cache_enabled: bool = True
    price_history_cache_ttl_seconds: int = 24 * 60 * 60
    monthly_revenue_cache_ttl_seconds: int = 7 * 24 * 60 * 60
    financial_metrics_cache_ttl_seconds: int = 31 * 24 * 60 * 60
    valuation_metrics_cache_ttl_seconds: int = 24 * 60 * 60
    market_price_provider_order: str = "finmind,fugle"
    finmind_public_fallback_enabled: bool = True
    finmind_max_retries: int = 2
    finmind_base_retry_delay_seconds: float = 0.5
    finmind_max_retry_delay_seconds: float = 5.0
    finmind_timeout_seconds: float = 20.0
    finmind_connect_timeout_seconds: float = 8.0
    finmind_concurrency: int = 5
    finmind_circuit_breaker_enabled: bool = True
    finmind_circuit_breaker_failure_threshold: int = 5
    finmind_circuit_breaker_recovery_seconds: float = 60.0
    fugle_max_retries: int = 2
    fugle_base_retry_delay_seconds: float = 0.5
    fugle_max_retry_delay_seconds: float = 5.0
    fugle_timeout_seconds: float = 20.0
    fugle_connect_timeout_seconds: float = 8.0
    fugle_circuit_breaker_enabled: bool = True
    fugle_circuit_breaker_failure_threshold: int = 5
    fugle_circuit_breaker_recovery_seconds: float = 60.0
    market_official_openapi_fallback_enabled: bool = True
    market_official_openapi_timeout_seconds: float = 15.0
    company_filing_user_agents: str = ""
    company_filing_proxy_urls: str = ""
    company_filing_http_retries: int = 1
    company_filing_base_retry_delay_seconds: float = 0.5
    company_filing_max_retry_delay_seconds: float = 5.0
    company_filing_pdf_parser: str = "auto"
    company_filing_pdf_extract_tables: bool = True
    company_filing_html_extract_tables: bool = True
    company_filing_cache_enabled: bool = True
    company_filing_cache_ttl_seconds: int = 7 * 24 * 60 * 60
    company_filing_browser_render_enabled: bool = False
    company_filing_browser_render_url: str = ""
    company_filing_browser_render_token: str = ""
    company_filing_browser_render_timeout_seconds: float = 30.0
    company_filing_browser_render_concurrency: int = 4
    company_filing_playwright_render_enabled: bool = False
    company_filing_playwright_browser: str = "chromium"
    company_filing_playwright_wait_until: str = "networkidle"
    company_filing_playwright_timeout_seconds: float = 30.0
    vector_db_path: Path = Path(".chroma")
    use_chroma: bool = False
    chroma_api_url: str = ""
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "default_database"
    rag_embedding_provider: str = "sentence_transformers"
    rag_embedding_model: str = "intfloat/multilingual-e5-large"
    rag_embedding_output_dimensionality: Optional[int] = None
    rag_index_schema_version: str = "identity-v2"
    rag_allow_chroma_default_embedding_fallback: bool = False
    rag_hybrid_search_enabled: bool = True
    rag_vector_weight: float = 0.60
    rag_keyword_weight: float = 0.40
    rag_rerank_top_k: int = 40
    rag_keyword_corpus_limit: int = 2000
    rag_chroma_query_timeout_seconds: float = 12.0
    rag_chroma_get_timeout_seconds: float = 8.0
    rag_chroma_upsert_timeout_seconds: float = 30.0
    rag_reranker_provider: str = "auto"
    rag_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rag_reranker_text_limit: int = 4000
    rag_reranker_timeout_seconds: float = 15.0
    rag_llm_reranker_enabled: bool = True
    rag_llm_reranker_max_documents: int = 12
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: Optional[str] = None
    neo4j_database: str = ""
    neo4j_timeout_seconds: float = 15.0
    neo4j_status_check_connection: bool = True
    report_dir: Path = Path("reports")
    scoring_config_path: Path = Path("data/scoring_config.toml")
    api_base_url: str = "http://127.0.0.1:8000"
    schedule_config_path: Path = Path("data/schedule_config.json")
    news_sources_path: Path = Path("data/news_sources.json")
    whitelist_path: Path = Path("data/ai_supply_chain_whitelist.json")
    primary_llm_model: str = "gemini-3.5-flash"
    local_llm_model: str = "gemma-4-31b-it"
    llm_provider: str = "litellm"
    llm_fallback_models: str = "gemini-2.5-flash-lite,gemma-4-31b-it"
    google_api_key: Optional[str] = None
    google_api_keys: str = ""
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    cohere_api_key: Optional[str] = None
    fugle_api_key: Optional[str] = None
    finmind_token: Optional[str] = None
    candidate_confidence_high_threshold: int = 75
    candidate_confidence_medium_threshold: int = 45
    llm_max_retries_per_key: int = 2
    llm_base_retry_delay_seconds: float = 0.5
    llm_max_retry_delay_seconds: float = 5.0
    llm_total_timeout_seconds: float = 60.0
    auto_follow_up_enabled: bool = True
    auto_follow_up_news_limit: int = 30
    sync_report_pre_refresh_enabled: bool = False
    report_quality_auto_recovery_enabled: bool = True
    workflow_engine: str = "local"
    workflow_local_fallback_enabled: bool = True
    prefect_api_url: str = ""
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "stock-analysis"
    temporal_workflow_name: str = "StockAnalysisPipeline"
    temporal_ui_url: str = ""
    temporal_timeout_seconds: float = 15.0
    airflow_api_url: str = ""
    airflow_dag_id: str = "stock_analysis_pipeline"
    airflow_api_token: Optional[str] = None
    airflow_username: str = ""
    airflow_password: Optional[str] = None
    airflow_timeout_seconds: float = 15.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )

    @property
    def gemini_api_keys(self) -> list[str]:
        keys = [key.strip() for key in self.google_api_keys.split(",") if key.strip()]
        if self.google_api_key:
            keys.append(self.google_api_key.strip())
        return list(dict.fromkeys(keys))


@lru_cache
def get_settings() -> Settings:
    return Settings()
