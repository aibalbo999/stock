from __future__ import annotations

from app.services.external_deployment_env_items import service_snapshot_external_env_items


def test_service_snapshot_external_env_items_maps_status_snapshot_to_readiness_items() -> None:
    service_snapshot = {
        "supply_chain_graph": {
            "neo4j_import": {
                "ready": False,
                "fallback_reason": "missing_settings:neo4j_uri",
            }
        },
        "company_filings": {
            "browser_render_runtime": {
                "configuration_ready": False,
                "missing_env_keys": ["COMPANY_FILING_BROWSER_RENDER_URL"],
            },
            "high_risk_source_policy": {
                "high_risk_mitigation_ready": False,
                "configuration_check": {
                    "missing_env_keys": ["COMPANY_FILING_BROWSER_RENDER_PROVIDER"]
                },
            },
            "structured_api_runtime": {
                "configuration_ready": False,
                "configuration_check": {"missing_env_keys": ["COMPANY_FILING_STRUCTURED_API_URL"]},
            },
            "visual_rag_runtime": {
                "runtime_available": False,
                "fallback_reason": "missing_vision_llm_key_or_gateway",
            },
        },
    }

    items = service_snapshot_external_env_items(service_snapshot)
    items_by_capability = {item["capability"]: item for item in items}

    assert list(items_by_capability) == [
        "neo4j_import",
        "company_filing_browser_or_proxy_fallback",
        "company_filing_high_risk_unlocker",
        "company_filing_structured_api_fallback",
        "visual_rag",
    ]
    assert items_by_capability["neo4j_import"]["area"] == "ai_rag"
    assert items_by_capability["neo4j_import"]["label"] == "Neo4j / GraphRAG live graph"
    assert items_by_capability["neo4j_import"]["_env_source"] == "/services/status"
    assert items_by_capability["company_filing_high_risk_unlocker"]["optional"] is True
    assert items_by_capability["company_filing_structured_api_fallback"]["evidence"] == {
        "runtime": service_snapshot["company_filings"]["structured_api_runtime"]
    }
    assert items_by_capability["visual_rag"]["optional"] is True


def test_service_snapshot_external_env_items_ignores_invalid_snapshots() -> None:
    assert service_snapshot_external_env_items(None) == []
    assert service_snapshot_external_env_items({"company_filings": []}) == []
