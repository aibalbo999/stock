from __future__ import annotations

from scripts.external_integrations_smoke import (
    external_integration_report,
    format_external_integration_report,
)


def test_external_integration_report_summarizes_optional_deployment_checks() -> None:
    report = external_integration_report(
        {
            "upgrade_capability_matrix": {
                "ai_rag": {
                    "neo4j_payload_export": {
                        "status": "ready",
                        "evidence": {
                            "payload_export_ready": True,
                            "payload_format": "neo4j_cypher_v1",
                            "payload_node_count": 27,
                            "payload_statement_count": 5,
                        },
                    },
                    "graphrag_agentic_cypher": {
                        "status": "ready",
                        "evidence": {
                            "local_dry_run_enabled": True,
                            "local_dry_run_status": "executed_dry_run",
                            "agentic_cypher_plan_example": {
                                "validation": {"valid": True, "read_only": True},
                            },
                        },
                    },
                    "neo4j_import": {
                        "status": "degraded",
                        "evidence": {
                            "fallback_reason": "missing",
                            "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
                            "import_smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --json",
                            "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
                        },
                    },
                    "graphrag_live_cypher_query": {"status": "degraded", "evidence": {}},
                },
                "data_business_logic": {
                    "company_filing_browser_or_proxy_fallback": {
                        "status": "ready",
                        "evidence": {
                            "playwright_render_runtime": {
                                "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json"
                            },
                            "high_risk_source_policy": {
                                "smoke_cli": (
                                    ".venv/bin/python scripts/company_filing_render_smoke.py "
                                    "--url https://mops.twse.com.tw/ --json"
                                )
                            },
                        },
                    },
                    "company_filing_high_risk_unlocker": {
                        "status": "not_configured",
                        "evidence": {
                            "configured_provider": "browserless",
                            "smoke_cli": (
                                ".venv/bin/python scripts/company_filing_render_smoke.py "
                                "--url https://mops.twse.com.tw/ --json"
                            ),
                        },
                    },
                    "company_filing_structured_api_fallback": {
                        "status": "not_configured",
                        "evidence": {},
                    },
                },
            }
        }
    )

    assert report["status"] == "caution"
    assert report["ready_count"] == 5
    assert report["check_count"] == 9
    assert report["actionable_check_count"] == 9
    assert report["enablement_summary"]["total"] == 5
    assert report["enablement_summary"]["ready"] == 1
    assert report["enablement_summary"]["pending"] == 4
    assert report["enablement_summary"]["free_local_pending"] == 3
    assert report["enablement_summary"]["local_action_available"] == 3
    assert report["enablement_summary"]["quota_or_external_pending"] == 0
    assert report["enablement_summary"]["paid_external_pending"] == 1
    assert report["enablement_summary"]["primary_next_action"] == (
        "先處理本機免費可補強項目，再評估 API 額度或付費資料商。"
    )
    assert {check["capability"] for check in report["checks"]} == {
        "neo4j_payload_export_contract",
        "graphrag_local_cypher_dry_run",
        "neo4j_import",
        "graphrag_live_cypher_query",
        "company_filing_browser_or_proxy_fallback",
        "company_filing_high_risk_unlocker",
        "company_filing_structured_api_fallback",
        "company_filing_render_provider_contract",
        "company_filing_structured_api_sample_contract",
    }
    assert "start_system.py --start-dependencies" in report["local_start_command"]
    assert "neo4j_graphrag_smoke.py" in report["neo4j_graphrag_smoke_command"]
    assert "import-first" in report["neo4j_import_smoke_command"]
    assert "local-contract" in report["neo4j_local_contract_smoke_command"]
    assert "import_supply_chain_graph_neo4j --dry-run" in report["neo4j_payload_dry_run_command"]
    assert "company_filing_render_smoke.py" in report[
        "company_filing_render_smoke_command"
    ]
    assert "mops.twse.com.tw" in report[
        "high_risk_company_filing_render_smoke_command"
    ]
    assert "provider-contract" in report[
        "company_filing_render_provider_contract_command"
    ]
    assert "structured_company_filing_smoke.py" in report[
        "structured_company_filing_smoke_command"
    ]
    assert "structured_company_filing_sample.json" in report[
        "structured_company_filing_sample_command"
    ]
    assert report["structured_company_filing_sample_status"] == "ready"
    checks = {check["capability"]: check for check in report["checks"]}
    assert checks["neo4j_payload_export_contract"]["ready"] is True
    assert checks["neo4j_payload_export_contract"]["smoke_commands"] == [
        ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run"
    ]
    assert checks["graphrag_local_cypher_dry_run"]["ready"] is True
    assert checks["graphrag_local_cypher_dry_run"]["smoke_commands"] == [
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
        "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --local-contract --json"
    ]
    assert checks["neo4j_import"]["smoke_commands"] == [
        ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --json",
    ]
    assert checks["neo4j_import"]["enablement_profile"]["deployment_profile"] == "free_local"
    assert checks["neo4j_import"]["enablement_profile"]["group_label"] == "可本機免費啟用"
    assert checks["graphrag_live_cypher_query"]["smoke_commands"][0].endswith(
        "scripts.import_supply_chain_graph_neo4j --dry-run"
    )
    assert checks["company_filing_browser_or_proxy_fallback"]["smoke_commands"] == [
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    ]
    assert all(
        "mops.twse.com.tw" not in command
        for command in checks["company_filing_browser_or_proxy_fallback"]["smoke_commands"]
    )
    assert checks["company_filing_high_risk_unlocker"]["smoke_commands"] == [
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://mops.twse.com.tw/ --json"
    ]
    assert checks["company_filing_high_risk_unlocker"]["enablement_profile"][
        "free_local_available"
    ] is True
    assert "FlareSolverr 本機免費" in checks["company_filing_high_risk_unlocker"][
        "enablement_profile"
    ]["cost_label"]
    assert checks["company_filing_render_provider_contract"]["ready"] is True
    assert checks["company_filing_render_provider_contract"]["evidence"][
        "provider_count"
    ] == 5
    assert checks["company_filing_render_provider_contract"]["smoke_commands"] == [
        ".venv/bin/python scripts/company_filing_render_smoke.py --provider-contract --json"
    ]
    assert checks["company_filing_structured_api_fallback"]["smoke_commands"] == [
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
        "--sample-json examples/structured_company_filing_sample.json "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
    ]
    assert checks["company_filing_structured_api_fallback"]["enablement_profile"][
        "deployment_profile"
    ] == "paid_external"
    assert checks["company_filing_structured_api_fallback"]["enablement_profile"][
        "paid_service_required"
    ] is True
    assert checks["company_filing_structured_api_sample_contract"]["ready"] is True
    assert checks["company_filing_structured_api_sample_contract"]["evidence"]["mode"] == (
        "sample_json_contract"
    )
    assert checks["company_filing_structured_api_sample_contract"]["smoke_commands"] == [
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
        "--sample-json examples/structured_company_filing_sample.json "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    ]

    output = format_external_integration_report(report)

    assert "smoke:" in output
    assert "External integrations: caution (5/9 ready)" in output
    assert (
        "Enablement summary: pending=4; free_local=3; local_action=3; "
        "quota_or_external=0; paid_external=1"
    ) in output
    assert "Next action: 先處理本機免費可補強項目" in output
    assert "enablement: 可本機免費啟用" in output
    assert "enablement: 需外部資料 API" in output
    assert "Neo4j payload local contract: ready" in output
    assert "GraphRAG local guarded Cypher dry-run: ready" in output
    assert "--local-contract" in output
    assert "Company filing render provider contract: ready" in output
    assert "--provider-contract" in output
    assert "scripts.import_supply_chain_graph_neo4j --dry-run" in output
    assert "High-risk filing unlocker smoke" in output
    assert "https://mops.twse.com.tw/" in output
    assert "structured_company_filing_smoke.py" in output
    assert "structured_company_filing_sample.json" in output
    assert "Structured company filing sample contract: ready" in output
