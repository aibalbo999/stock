from __future__ import annotations

EXTERNAL_SMOKE_COMMAND_KEYS = frozenset(
    {
        "smoke_cli",
        "smoke_command",
        "smoke_commands",
        "sample_contract_cli",
        "payload_dry_run_cli",
        "import_smoke_cli",
        "neo4j_graphrag_smoke_command",
        "company_filing_render_smoke_command",
        "structured_company_filing_smoke_command",
    }
)
EXTERNAL_DETAIL_KEYS = frozenset(
    {
        "fallback_reason",
        "connection_error",
        "runtime_error",
        "error",
        "reason",
    }
)
EXTERNAL_READINESS_METADATA = {
    ("ai_rag", "neo4j_import"): {
        "priority": "P1",
        "impact": "GraphRAG payload 匯入與 live graph context。",
    },
    ("ai_rag", "graphrag_live_cypher_query"): {
        "priority": "P1",
        "impact": "LLM guarded Cypher、shortest-path 與上下游衝擊推理。",
    },
    ("ai_rag", "visual_rag"): {
        "priority": "P2",
        "impact": "掃描型 PDF、圖表與複雜財報頁面解析。",
    },
    ("data_business_logic", "company_filing_pdf_table_parser_runtime"): {
        "priority": "P2",
        "impact": "PDF 財報與法說會表格抽取品質。",
    },
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): {
        "priority": "P1",
        "impact": "動態頁、被擋頁與一般公司文件 render fallback。",
    },
    ("data_business_logic", "company_filing_high_risk_unlocker"): {
        "priority": "P0",
        "impact": "MOPS、doc.twse、TWSE/TPEx 高風險文件入口。",
    },
    ("data_business_logic", "company_filing_structured_api_fallback"): {
        "priority": "P1",
        "impact": "法說會簡報、重大訊息與專業財經資料備援。",
    },
}
EXTERNAL_LOCAL_ACTION_METADATA = {
    ("ai_rag", "neo4j_import"): {
        "wait_key": "neo4j",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-neo4j-defaults --wait-local-neo4j 20 --json"
        ),
    },
    ("ai_rag", "graphrag_live_cypher_query"): {
        "wait_key": "neo4j",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-neo4j-defaults --wait-local-neo4j 20 --json"
        ),
    },
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): {
        "wait_key": "browserless",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--wait-local-browserless 20 --local-browser-render-defaults --json"
        ),
    },
    ("data_business_logic", "company_filing_high_risk_unlocker"): {
        "wait_key": "flaresolverr",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--prefer-unlocker --wait-local-flaresolverr 20 "
            "--local-browser-render-defaults --json"
        ),
    },
}
EXTERNAL_ENABLEMENT_METADATA = {
    ("ai_rag", "neo4j_import"): {
        "group": "free_local_first",
        "group_label": "可本機免費啟用",
        "cost_profile": "free_local_or_managed",
        "cost_label": "本機 Neo4j 免費；託管 Neo4j 依方案",
        "recommended_path": "先啟動本機 Neo4j；正式部署再視流量改託管。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("ai_rag", "graphrag_live_cypher_query"): {
        "group": "free_local_first",
        "group_label": "可本機免費啟用",
        "cost_profile": "free_local_or_managed",
        "cost_label": "本機 Neo4j 免費；託管 Neo4j 依方案",
        "recommended_path": "先用本機 Neo4j 驗證 guarded Cypher；正式部署再接託管圖庫。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("ai_rag", "visual_rag"): {
        "group": "quota_or_local_model",
        "group_label": "API 額度或本機模型",
        "cost_profile": "free_quota_or_paid_tokens",
        "cost_label": "Gemini 免費額度可先用；大量 PDF 圖像解析會消耗額度或 API 成本",
        "recommended_path": "先限制 Visual RAG request budget，只對複雜 PDF 啟用。",
        "free_local_available": False,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_pdf_table_parser_runtime"): {
        "group": "free_python_runtime",
        "group_label": "免費 Python 套件",
        "cost_profile": "free_runtime_dependency",
        "cost_label": "pdfplumber/PyMuPDF 類套件免費；unstructured 可能需要較重系統依賴",
        "recommended_path": "先安裝輕量 parser；只有複雜表格再補 unstructured。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): {
        "group": "free_local_first",
        "group_label": "可本機免費啟用",
        "cost_profile": "free_local_or_paid_proxy",
        "cost_label": "Playwright/Browserless 本機免費；rotating proxy 可能付費",
        "recommended_path": "先用 Playwright 或 Browserless；遇到封鎖再加 proxy。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_high_risk_unlocker"): {
        "group": "free_local_or_paid_unlocker",
        "group_label": "本機免費或付費 unlocker",
        "cost_profile": "free_flaresolverr_or_paid_managed",
        "cost_label": "FlareSolverr 本機免費；ScrapingBee/BrightData 通常付費",
        "recommended_path": "先用本機 FlareSolverr；穩定正式部署再評估 managed unlocker。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_structured_api_fallback"): {
        "group": "paid_external_api",
        "group_label": "需外部資料 API",
        "cost_profile": "paid_contract_likely",
        "cost_label": "TEJ 或專業資料商通常需付費合約/API token",
        "recommended_path": (
            "免費版先保留 sample contract，並用本機 fixture API 驗證 live HTTP contract；"
            "只有需要穩定法說/重大訊息才接資料商。"
        ),
        "free_local_available": False,
        "paid_service_required": True,
    },
}

