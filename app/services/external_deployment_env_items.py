from __future__ import annotations

from typing import Any


def service_snapshot_external_env_items(service_snapshot: object) -> list[dict[str, Any]]:
    if not isinstance(service_snapshot, dict):
        return []
    items: list[dict[str, Any]] = []
    graph = (
        service_snapshot.get("supply_chain_graph")
        if isinstance(service_snapshot.get("supply_chain_graph"), dict)
        else {}
    )
    neo4j_import = graph.get("neo4j_import") if isinstance(graph.get("neo4j_import"), dict) else {}
    if neo4j_import and not neo4j_import.get("ready"):
        items.append(
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "Neo4j / GraphRAG live graph",
                "status": "degraded",
                "severity": "warn",
                "external_integration": True,
                "deployment_check": True,
                "evidence": neo4j_import,
                "remediation": "設定 NEO4J_URI / 帳密並啟動 Neo4j。",
                "_env_source": "/services/status",
            }
        )
    filings = (
        service_snapshot.get("company_filings")
        if isinstance(service_snapshot.get("company_filings"), dict)
        else {}
    )
    if filings:
        items.extend(_company_filing_env_items(filings))
    return items


def _company_filing_env_items(filings: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    browser_runtime = (
        filings.get("browser_render_runtime")
        if isinstance(filings.get("browser_render_runtime"), dict)
        else {}
    )
    if browser_runtime and not browser_runtime.get("configuration_ready"):
        items.append(
            _service_env_item(
                "company_filing_browser_or_proxy_fallback",
                "公司文件 Browser render 後援",
                browser_runtime,
                "補齊 Browser render provider / URL 後重跑文件 render smoke。",
            )
        )
    high_risk_policy = (
        filings.get("high_risk_source_policy")
        if isinstance(filings.get("high_risk_source_policy"), dict)
        else {}
    )
    if high_risk_policy and not high_risk_policy.get("high_risk_mitigation_ready"):
        items.append(
            _service_env_item(
                "company_filing_high_risk_unlocker",
                "MOPS/TWSE/TPEx 高風險文件 unlocker",
                high_risk_policy,
                "設定 FlareSolverr、ScrapingBee、BrightData 或 rotating proxy。",
                optional=True,
            )
        )
    structured_runtime = (
        filings.get("structured_api_runtime")
        if isinstance(filings.get("structured_api_runtime"), dict)
        else {}
    )
    if structured_runtime and not structured_runtime.get("configuration_ready"):
        items.append(
            _service_env_item(
                "company_filing_structured_api_fallback",
                "公司文件結構化 API 備援",
                {"runtime": structured_runtime},
                "設定 TEJ 或專業資料 API provider / URL / token。",
                optional=True,
            )
        )
    visual_runtime = (
        filings.get("visual_rag_runtime")
        if isinstance(filings.get("visual_rag_runtime"), dict)
        else {}
    )
    if visual_runtime and not visual_runtime.get("runtime_available"):
        items.append(
            {
                "area": "ai_rag",
                "capability": "visual_rag",
                "label": "Visual RAG / VLM 財報解析",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "deployment_check": True,
                "evidence": visual_runtime,
                "remediation": "確認 PyMuPDF、Visual RAG model 與 Gemini key pool。",
                "_env_source": "/services/status",
            }
        )
    return items


def _service_env_item(
    capability: str,
    label: str,
    evidence: dict[str, Any],
    remediation: str,
    *,
    optional: bool = False,
) -> dict[str, Any]:
    return {
        "area": "data_business_logic",
        "capability": capability,
        "label": label,
        "status": "not_configured",
        "severity": "warn",
        "optional": optional,
        "external_integration": True,
        "deployment_check": True,
        "evidence": evidence,
        "remediation": remediation,
        "_env_source": "/services/status",
    }
