from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptimizationCapabilityRef:
    area: str
    capability: str
    label: str
    optional: bool = False
    external: bool = False
    action_type: str = "code_or_config"
    next_action: str = ""


@dataclass(frozen=True)
class OptimizationDomain:
    id: str
    label: str
    objective: str
    capability_refs: tuple[OptimizationCapabilityRef, ...]
    long_term_note: str = ""


OPTIMIZATION_DOMAINS: tuple[OptimizationDomain, ...] = (
    OptimizationDomain(
        id="architecture_uiux",
        label="系統架構與前端體驗",
        objective="Streamlit MPA、外部 CSS、FastAPI/Celery 背景任務輪詢與可恢復 workflow。",
        capability_refs=(
            OptimizationCapabilityRef(
                "architecture",
                "streamlit_mpa_background_tasks",
                "Streamlit MPA 與背景任務輪詢",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "background_task_queue",
                "背景任務佇列就緒檢查",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "workflow_orchestration",
                "可恢復 workflow orchestration",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "latest_report_retention",
                "最新版報告保留策略",
            ),
        ),
        long_term_note="若正式開放多人使用，再評估把 Streamlit 前端遷移到 Next.js/Nuxt。",
    ),
    OptimizationDomain(
        id="codebase_maintainability",
        label="程式碼結構與維護性",
        objective="API controller 維持 thin entry，業務邏輯下放 service，安全掃描使用外部工具。",
        capability_refs=(
            OptimizationCapabilityRef(
                "architecture",
                "thin_api_controller",
                "API controller/service 分層",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "database_migrations",
                "Alembic database migrations",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "secret_scanning",
                "外部密鑰掃描工具整合",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "source_quality_weighting",
                "來源可信度分層與低品質來源降權",
            ),
        ),
        long_term_note="Legacy alias 只保留相容舊測試/腳本；新功能應繼續從 router 呼叫 service/use case。",
    ),
    OptimizationDomain(
        id="data_pipeline_scraping",
        label="資料管線與爬蟲穩定度",
        objective="市場資料快取/來源 fallback、公司文件 render/unlocker、官方 OpenAPI 與結構化 API 備援。",
        capability_refs=(
            OptimizationCapabilityRef(
                "data_business_logic",
                "market_data_cache",
                "Redis 市場/財務資料快取",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "market_data_provider_fallback",
                "FinMind/Fugle/官方 OpenAPI fallback",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_fetch_hardening",
                "公司文件反爬蟲與 PDF/HTML 表格解析",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_render_provider_contract",
                "公司文件渲染/解鎖提供者格式檢查",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_official_material_information_openapi",
                "TWSE/TPEx 官方重大訊息 OpenAPI fallback",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_structured_api_sample_contract",
                "公司文件結構化 API 樣本資料格式檢查",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_cache",
                "公司文件 URL 解析快取",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_browser_or_proxy_fallback",
                "公司文件 Proxy / Browser render / Playwright 後援",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="正式部署若常遇到動態頁或空殼頁，再設定 Browserless/Proxy/Playwright。",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_high_risk_unlocker",
                "MOPS/TWSE/TPEx 高風險文件 unlocker",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="高風險 MOPS/TWSE 文件被擋時，優先啟用 FlareSolverr，再評估 ScrapingBee/BrightData。",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_structured_api_fallback",
                "公司文件結構化 API 備援",
                optional=True,
                external=True,
                action_type="paid_external",
                next_action="只有需要穩定法說會簡報/重大訊息時，才接 TEJ 或專業資料 API。",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_pdf_table_parser_runtime",
                "PDF 表格 parser runtime",
                optional=True,
                action_type="local_dependency",
                next_action='需要更多 PDF 表格抽取時安裝 pip install -e ".[pdf]"。',
            ),
        ),
    ),
    OptimizationDomain(
        id="ai_rag_graphrag",
        label="AI、RAG 與知識圖譜",
        objective="免費額度感知模型路由、hybrid retrieval/reranker、GraphRAG 推理、Visual RAG 與 observability。",
        capability_refs=(
            OptimizationCapabilityRef(
                "ai_rag",
                "multilingual_embedding",
                "明確使用繁中/多語 embedding",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "llm_sdk_and_fallback",
                "LLM SDK 與模型降級能力",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "llm_quota_routing",
                "免費額度感知模型路由",
            ),
            OptimizationCapabilityRef("ai_rag", "hybrid_search", "Hybrid Search / BM25 關鍵字檢索"),
            OptimizationCapabilityRef("ai_rag", "reranking", "模型級 reranking"),
            OptimizationCapabilityRef("ai_rag", "llm_observability", "LLM/RAG observability"),
            OptimizationCapabilityRef("ai_rag", "graphrag_context", "GraphRAG 檢索脈絡"),
            OptimizationCapabilityRef(
                "ai_rag",
                "graphrag_path_reasoning",
                "GraphRAG shortest-path 推理脈絡",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "graphrag_agentic_cypher",
                "GraphRAG guarded LLM Cypher planner",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "neo4j_payload_export",
                "Neo4j 參數化匯入資料輸出",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "visual_rag",
                "Visual RAG / VLM 財報解析",
                optional=True,
                external=True,
                action_type="quota_or_external",
                next_action="需要處理掃描型或複雜表格 PDF 時，再配置 vision-capable 模型與額度。",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "neo4j_import",
                "外部 Neo4j 匯入連線",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="正式部署需要圖譜匯入時，設定 Neo4j URI/帳密並執行本機驗證。",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "graphrag_live_cypher_query",
                "GraphRAG 受控 Neo4j 查詢",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="正式部署要讓受控 Cypher 直接查 Neo4j 時，再啟用 Neo4j 查詢。",
            ),
        ),
    ),
)
