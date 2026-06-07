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
                            }
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
    assert report["ready_count"] == 1
    assert report["check_count"] == 4
    assert report["actionable_check_count"] == 4
    assert {check["capability"] for check in report["checks"]} == {
        "neo4j_import",
        "graphrag_live_cypher_query",
        "company_filing_browser_or_proxy_fallback",
        "company_filing_structured_api_fallback",
    }
    assert "start_system.py --start-dependencies" in report["local_start_command"]
    assert "neo4j_graphrag_smoke.py" in report["neo4j_graphrag_smoke_command"]
    assert "import-first" in report["neo4j_import_smoke_command"]
    assert "import_supply_chain_graph_neo4j --dry-run" in report["neo4j_payload_dry_run_command"]
    assert "company_filing_render_smoke.py" in report[
        "company_filing_render_smoke_command"
    ]
    assert "structured_company_filing_smoke.py" in report[
        "structured_company_filing_smoke_command"
    ]
    assert "structured_company_filing_sample.json" in report[
        "structured_company_filing_sample_command"
    ]
    checks = {check["capability"]: check for check in report["checks"]}
    assert checks["neo4j_import"]["smoke_commands"] == [
        ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
        ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --json",
    ]
    assert checks["graphrag_live_cypher_query"]["smoke_commands"][0].endswith(
        "scripts.import_supply_chain_graph_neo4j --dry-run"
    )
    assert checks["company_filing_browser_or_proxy_fallback"]["smoke_commands"] == [
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    ]
    assert checks["company_filing_structured_api_fallback"]["smoke_commands"] == [
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
        "--sample-json examples/structured_company_filing_sample.json "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
        "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json",
    ]

    output = format_external_integration_report(report)

    assert "smoke:" in output
    assert "scripts.import_supply_chain_graph_neo4j --dry-run" in output
    assert "structured_company_filing_smoke.py" in output
    assert "structured_company_filing_sample.json" in output
