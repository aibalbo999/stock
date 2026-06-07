from __future__ import annotations

from scripts.external_integrations_smoke import external_integration_report


def test_external_integration_report_summarizes_optional_deployment_checks() -> None:
    report = external_integration_report(
        {
            "upgrade_capability_matrix": {
                "ai_rag": {
                    "neo4j_import": {"status": "degraded", "evidence": {"fallback_reason": "missing"}},
                    "graphrag_live_cypher_query": {"status": "degraded", "evidence": {}},
                },
                "data_business_logic": {
                    "company_filing_browser_or_proxy_fallback": {"status": "ready", "evidence": {}},
                    "company_filing_structured_api_fallback": {"status": "not_configured", "evidence": {}},
                },
            }
        }
    )

    assert report["status"] == "caution"
    assert report["ready_count"] == 1
    assert report["check_count"] == 4
    assert {check["capability"] for check in report["checks"]} == {
        "neo4j_import",
        "graphrag_live_cypher_query",
        "company_filing_browser_or_proxy_fallback",
        "company_filing_structured_api_fallback",
    }
    assert "start_system.py --start-dependencies" in report["local_start_command"]
