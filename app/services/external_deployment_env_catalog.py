from __future__ import annotations


EXTERNAL_ENV_KEY_HINTS = {
    "NEO4J_URI": {
        "default": "neo4j://localhost:7687",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "NEO4J_USER": {
        "default": "neo4j",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "NEO4J_PASSWORD": {
        "default": "<password>",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "NEO4J_DATABASE": {
        "default": "neo4j",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "COMPANY_FILING_BROWSER_RENDER_ENABLED": {
        "default": "true",
        "scope": "公司文件 browser render / unlocker",
    },
    "COMPANY_FILING_BROWSER_RENDER_PROVIDER": {
        "default": "flaresolverr",
        "scope": "公司文件 browser render / unlocker",
    },
    "COMPANY_FILING_BROWSER_RENDER_URL": {
        "default": "http://127.0.0.1:8191/v1",
        "scope": "公司文件 browser render / unlocker",
    },
    "COMPANY_FILING_BROWSER_RENDER_TOKEN": {
        "default": "<token>",
        "scope": "ScrapingBee / BrightData managed unlocker",
    },
    "COMPANY_FILING_PROXY_URLS": {
        "default": "<rotating-proxy-list>",
        "scope": "高風險公開文件 IP rotation",
    },
    "COMPANY_FILING_STRUCTURED_API_PROVIDER": {
        "default": "tej",
        "scope": "公司文件結構化 API 備援",
    },
    "COMPANY_FILING_STRUCTURED_API_URL": {
        "default": "<provider-json-endpoint>",
        "scope": "公司文件結構化 API 備援",
    },
    "COMPANY_FILING_STRUCTURED_API_TOKEN": {
        "default": "<token>",
        "scope": "TEJ / 專業財經資料 API",
    },
    "COMPANY_FILING_VISUAL_RAG_ENABLED": {
        "default": "true",
        "scope": "PDF 圖表與複雜表格 VLM fallback",
    },
    "COMPANY_FILING_VISUAL_RAG_MODEL": {
        "default": "gemini-3.5-flash",
        "scope": "PDF 圖表與複雜表格 VLM fallback",
    },
    "GOOGLE_API_KEY": {
        "default": "<token>",
        "scope": "Gemini / Visual RAG / LLM fallback",
    },
    "GOOGLE_API_KEYS": {
        "default": "<token1>,<token2>",
        "scope": "Gemini / Visual RAG / LLM fallback",
    },
}
EXTERNAL_CAPABILITY_ENV_DEFAULTS = {
    ("ai_rag", "neo4j_import"): (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
    ),
    ("ai_rag", "graphrag_live_cypher_query"): (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
    ),
    ("ai_rag", "visual_rag"): (
        "COMPANY_FILING_VISUAL_RAG_ENABLED",
        "COMPANY_FILING_VISUAL_RAG_MODEL",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEYS",
    ),
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): (
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PROXY_URLS",
    ),
    ("data_business_logic", "company_filing_high_risk_unlocker"): (
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_BROWSER_RENDER_TOKEN",
        "COMPANY_FILING_PROXY_URLS",
    ),
    ("data_business_logic", "company_filing_structured_api_fallback"): (
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
        "COMPANY_FILING_STRUCTURED_API_TOKEN",
    ),
}
EXTERNAL_ENV_CHECK_TARGETS = ("host", "compose")
COMPOSE_ENV_VALUE_DEFAULTS = {
    "NEO4J_URI": "neo4j://neo4j:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "<password>",
    "NEO4J_DATABASE": "neo4j",
}


def external_env_key_hint(env_key: str) -> dict:
    return dict(EXTERNAL_ENV_KEY_HINTS.get(env_key, {}))


def external_capability_env_defaults(area: str, capability: str) -> tuple[str, ...]:
    return EXTERNAL_CAPABILITY_ENV_DEFAULTS.get((str(area), str(capability)), ())


def external_env_compose_recommended_value(
    env_key: str,
    recommended_value: str,
    compose_recommendations: dict[str, str],
) -> str:
    if env_key in compose_recommendations:
        return compose_recommendations[env_key]
    return COMPOSE_ENV_VALUE_DEFAULTS.get(env_key, recommended_value)
