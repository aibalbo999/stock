from __future__ import annotations

import json
import os

from app.core.config import get_settings
from app.services.supply_chain_graph_neo4j import LOCAL_NEO4J_ENV_DEFAULTS
import scripts.external_integrations_smoke as smoke
from scripts.external_integrations_smoke import (
    external_integration_report,
    format_external_integration_report,
)

LOCAL_BROWSER_RENDER_ENV_KEYS = (
    "COMPANY_FILING_PROXY_URLS",
    "COMPANY_FILING_BROWSER_RENDER_ENABLED",
    "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
    "COMPANY_FILING_BROWSER_RENDER_URL",
    "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
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
                                    "--local-browser-render-defaults --prefer-unlocker "
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
                                "--local-browser-render-defaults --prefer-unlocker "
                                "--url https://mops.twse.com.tw/ --json"
                            ),
                        },
                    },
                    "company_filing_structured_api_fallback": {
                        "status": "not_configured",
                        "evidence": {},
                    },
                },
            },
            "local_dependency_auto_defaults": {
                "capability_matches": [
                    {
                        "area": "ai_rag",
                        "capability": "neo4j_import",
                        "group": "neo4j",
                        "state": "would_apply",
                        "would_apply": True,
                        "verify_command": (
                            ".venv/bin/python scripts/upgrade_audit.py "
                            "--auto-local-defaults --json"
                        ),
                    },
                    {
                        "area": "ai_rag",
                        "capability": "graphrag_live_cypher_query",
                        "group": "neo4j",
                        "state": "would_apply",
                        "would_apply": True,
                        "verify_command": (
                            ".venv/bin/python scripts/upgrade_audit.py "
                            "--auto-local-defaults --json"
                        ),
                    },
                    {
                        "area": "data_business_logic",
                        "capability": "company_filing_high_risk_unlocker",
                        "group": "flaresolverr",
                        "state": "would_apply",
                        "would_apply": True,
                        "verify_command": (
                            ".venv/bin/python scripts/upgrade_audit.py "
                            "--auto-local-defaults --json"
                        ),
                    },
                ],
            },
            "local_dependencies": {
                "ports": [
                    {"service": "neo4j", "open": True},
                    {"service": "flaresolverr", "open": True},
                ],
            },
        },
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
    assert report["pending_gap_action_counts"] == {
        "local_action": 3,
        "quota_or_external": 0,
        "paid_external": 1,
        "manual_configuration": 0,
    }
    assert report["local_projection"]["current_pending"] == 4
    assert report["local_projection"]["available_local_default_gap_count"] == 3
    assert report["local_projection"]["remaining_pending"] == 1
    assert report["local_projection"]["remaining_blocking_pending"] == 0
    assert report["local_projection"]["remaining_optional_pending"] == 1
    assert report["local_projection"]["remaining_paid_external_pending"] == 1
    assert report["local_projection"]["remaining_capabilities"] == [
        {
            "area": "data_business_logic",
            "capability": "company_filing_structured_api_fallback",
            "label": "Structured company filing API fallback",
            "action_type": "paid_external",
        }
    ]
    assert "有效剩餘 1 項付費外部資料 API 選配" in report["local_projection"][
        "next_action"
    ]
    assert [row["capability"] for row in report["pending_gap_rows"]] == [
        "company_filing_high_risk_unlocker",
        "graphrag_live_cypher_query",
        "neo4j_import",
        "company_filing_structured_api_fallback",
    ]
    assert [row["action_type"] for row in report["pending_gap_rows"]] == [
        "local_action",
        "local_action",
        "local_action",
        "paid_external",
    ]
    assert report["pending_gap_rows"][0]["local_action_state"] == "端口已啟動，需驗證"
    assert "--wait-local-flaresolverr 20" in report["pending_gap_rows"][0][
        "local_action_command"
    ]
    assert report["pending_gap_rows"][-1]["deployment_profile"] == "paid_external"
    assert "TEJ" in report["pending_gap_rows"][-1]["cost_label"]
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
    assert "--provider-profile tej" in report[
        "structured_company_filing_local_provider_profile_smoke_command"
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
    assert checks["neo4j_import"]["enablement_profile"]["free_validation_available"] is True
    assert checks["neo4j_import"]["enablement_profile"]["free_validation_label"] == (
        "本機 smoke 可驗證"
    )
    assert any(
        "upgrade_audit.py --local-neo4j-defaults" in command
        for command in checks["neo4j_import"]["enablement_profile"][
            "free_validation_commands"
        ]
    )
    assert checks["graphrag_live_cypher_query"]["smoke_commands"][0].endswith(
        "scripts.import_supply_chain_graph_neo4j --dry-run"
    )
    assert checks["graphrag_live_cypher_query"]["enablement_profile"][
        "free_validation_available"
    ] is True
    assert checks["company_filing_browser_or_proxy_fallback"]["smoke_commands"] == [
        ".venv/bin/python scripts/company_filing_render_smoke.py --url https://example.com/ --json"
    ]
    assert all(
        "mops.twse.com.tw" not in command
        for command in checks["company_filing_browser_or_proxy_fallback"]["smoke_commands"]
    )
    assert checks["company_filing_high_risk_unlocker"]["smoke_commands"] == [
        (
            ".venv/bin/python scripts/company_filing_render_smoke.py "
            "--local-browser-render-defaults --prefer-unlocker "
            "--url https://mops.twse.com.tw/ --json"
        )
    ]
    assert checks["company_filing_high_risk_unlocker"]["enablement_profile"][
        "free_local_available"
    ] is True
    assert checks["company_filing_high_risk_unlocker"]["enablement_profile"][
        "free_validation_available"
    ] is True
    assert any(
        "--prefer-unlocker" in command
        for command in checks["company_filing_high_risk_unlocker"][
            "enablement_profile"
        ]["free_validation_commands"]
    )
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
        ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
        "--provider-profile tej --json --strict",
        "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom "
        "COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings "
        ".venv/bin/python scripts/structured_company_filing_smoke.py "
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
    assert (
        "Pending gap actions: local_action=3; quota_or_external=0; "
        "paid_external=1; manual_configuration=0"
    ) in output
    assert (
        "Effective gaps: pending=4 -> 1 after available local defaults; "
        "blocking=0; optional=1; paid_external=1; local_defaults=3"
    ) in output
    assert "Effective next action: 套用已偵測本機 defaults 可先消除 3 項缺口" in output
    assert "action: local_action" in output
    assert "action: paid_external" in output
    assert "command: .venv/bin/python scripts/upgrade_audit.py --prefer-unlocker" in output
    assert "端口已啟動，需驗證" in output
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
    assert "--provider-profile tej" in output
    assert "structured_company_filing_sample.json" in output
    assert "公司文件結構化樣本資料格式檢查: ready" in output
    assert "sample contract" not in output


def test_external_integration_report_can_use_local_neo4j_smoke_commands() -> None:
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
                        "status": "ready",
                        "evidence": {
                            "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
                            "import_smoke_cli": (
                                ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                                "--import-first --json"
                            ),
                            "payload_dry_run_cli": (
                                ".venv/bin/python -m "
                                "scripts.import_supply_chain_graph_neo4j --dry-run"
                            ),
                        },
                    },
                    "graphrag_live_cypher_query": {
                        "status": "ready",
                        "evidence": {
                            "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json"
                        },
                    },
                },
                "data_business_logic": {
                    "company_filing_browser_or_proxy_fallback": {
                        "status": "ready",
                        "evidence": {},
                    },
                    "company_filing_high_risk_unlocker": {
                        "status": "not_configured",
                        "evidence": {},
                    },
                    "company_filing_structured_api_fallback": {
                        "status": "not_configured",
                        "evidence": {},
                    },
                },
            }
        },
        local_neo4j_defaults={
            "requested": True,
            "applied_env_keys": ["NEO4J_URI"],
            "note": "Defaults apply only to this smoke process; .env is unchanged.",
        },
    )

    checks = {check["capability"]: check for check in report["checks"]}

    assert "--local-neo4j-defaults" in report["neo4j_graphrag_smoke_command"]
    assert "--local-neo4j-defaults" in report["neo4j_import_smoke_command"]
    assert "--local-neo4j-defaults" in checks["neo4j_import"]["smoke_commands"][1]
    assert "--local-neo4j-defaults" in checks["neo4j_import"]["smoke_commands"][2]
    assert any(
        "--local-neo4j-defaults" in command
        for command in checks["graphrag_live_cypher_query"]["smoke_commands"]
    )
    assert "local_neo4j_defaults" in report

    output = format_external_integration_report(report)

    assert "Local Neo4j defaults: applied NEO4J_URI" in output
    assert "Neo4j GraphRAG smoke: .venv/bin/python scripts/neo4j_graphrag_smoke.py --local-neo4j-defaults" in output


def test_external_integration_report_surfaces_local_browser_render_defaults() -> None:
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
                    "neo4j_import": {"status": "degraded", "evidence": {}},
                    "graphrag_live_cypher_query": {"status": "degraded", "evidence": {}},
                },
                "data_business_logic": {
                    "company_filing_browser_or_proxy_fallback": {
                        "status": "ready",
                        "evidence": {},
                    },
                    "company_filing_high_risk_unlocker": {
                        "status": "ready",
                        "evidence": {
                            "configured_provider": "flaresolverr",
                            "smoke_cli": (
                                ".venv/bin/python scripts/company_filing_render_smoke.py "
                                "--local-browser-render-defaults --prefer-unlocker "
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
        },
        local_browser_render_defaults={
            "requested": True,
            "preferred_unlocker": True,
            "browserless_port_available": False,
            "flaresolverr_port_available": True,
            "applied_env_keys": [
                "COMPANY_FILING_BROWSER_RENDER_ENABLED",
                "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
                "COMPANY_FILING_BROWSER_RENDER_URL",
            ],
            "note": "Defaults apply only to this smoke process; .env is unchanged.",
            "reason": None,
        },
        local_dependency_wait={
            "flaresolverr": True,
            "flaresolverr_timeout_seconds": 20,
        },
    )

    assert report["local_browser_render_defaults"]["preferred_unlocker"] is True
    assert report["local_unlocker_smoke_command"].endswith(
        "--local-browser-render-defaults --prefer-unlocker --wait-local-flaresolverr 20 --json"
    )

    output = format_external_integration_report(report)

    assert "Local browser render defaults: applied COMPANY_FILING_BROWSER_RENDER_ENABLED" in output
    assert "Local FlareSolverr wait: ready within 20s" in output
    assert "MOPS/TWSE/TPEx high-risk filing unlocker: ready" in output


def test_external_integrations_smoke_main_applies_local_neo4j_defaults(
    monkeypatch,
    capsys,
) -> None:
    old_env = {key: os.environ.get(key) for key in LOCAL_NEO4J_ENV_DEFAULTS}
    for key in LOCAL_NEO4J_ENV_DEFAULTS:
        os.environ.pop(key, None)
    get_settings.cache_clear()

    def fake_service_status() -> dict:
        settings = get_settings()
        assert settings.neo4j_uri == LOCAL_NEO4J_ENV_DEFAULTS["NEO4J_URI"]
        assert settings.neo4j_user == LOCAL_NEO4J_ENV_DEFAULTS["NEO4J_USER"]
        assert settings.neo4j_password == LOCAL_NEO4J_ENV_DEFAULTS["NEO4J_PASSWORD"]
        return {
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
                    "neo4j_import": {"status": "ready", "evidence": {}},
                    "graphrag_live_cypher_query": {"status": "ready", "evidence": {}},
                },
                "data_business_logic": {
                    "company_filing_browser_or_proxy_fallback": {
                        "status": "ready",
                        "evidence": {},
                    },
                    "company_filing_high_risk_unlocker": {
                        "status": "not_configured",
                        "evidence": {},
                    },
                    "company_filing_structured_api_fallback": {
                        "status": "not_configured",
                        "evidence": {},
                    },
                },
            }
        }

    monkeypatch.setattr(smoke, "service_status", fake_service_status)
    try:
        exit_code = smoke.main(["--local-neo4j-defaults", "--json"])
        report = json.loads(capsys.readouterr().out)
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    assert exit_code == 0
    assert report["local_neo4j_defaults"]["applied_env_keys"] == sorted(
        LOCAL_NEO4J_ENV_DEFAULTS
    )
    assert "--local-neo4j-defaults" in report["neo4j_graphrag_smoke_command"]


def test_external_integrations_smoke_main_applies_local_unlocker_defaults(
    monkeypatch,
    capsys,
) -> None:
    old_env = {key: os.environ.get(key) for key in LOCAL_BROWSER_RENDER_ENV_KEYS}
    for key in LOCAL_BROWSER_RENDER_ENV_KEYS:
        os.environ.pop(key, None)
    get_settings.cache_clear()

    def fake_wait_for_port(host: str, port: int, timeout_seconds: int) -> bool:
        return port == smoke.LOCAL_FLARESOLVERR_PORT

    def fake_is_port_open(host: str, port: int) -> bool:
        return port == smoke.LOCAL_FLARESOLVERR_PORT

    def fake_service_status() -> dict:
        settings = get_settings()
        assert settings.company_filing_browser_render_enabled is True
        assert settings.company_filing_browser_render_provider == "flaresolverr"
        assert settings.company_filing_browser_render_url == "http://127.0.0.1:8191/v1"
        return {
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
                    "neo4j_import": {"status": "ready", "evidence": {}},
                    "graphrag_live_cypher_query": {"status": "ready", "evidence": {}},
                },
                "data_business_logic": {
                    "company_filing_browser_or_proxy_fallback": {
                        "status": "ready",
                        "evidence": {},
                    },
                    "company_filing_high_risk_unlocker": {
                        "status": "ready",
                        "evidence": {},
                    },
                    "company_filing_structured_api_fallback": {
                        "status": "not_configured",
                        "evidence": {},
                    },
                },
            }
        }

    monkeypatch.setattr(smoke, "wait_for_port", fake_wait_for_port)
    monkeypatch.setattr(smoke, "is_port_open", fake_is_port_open)
    monkeypatch.setattr(smoke, "service_status", fake_service_status)
    try:
        exit_code = smoke.main(
            [
                "--local-browser-render-defaults",
                "--prefer-unlocker",
                "--wait-local-flaresolverr",
                "3",
                "--json",
            ]
        )
        report = json.loads(capsys.readouterr().out)
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    assert exit_code == 0
    assert report["local_browser_render_defaults"]["preferred_unlocker"] is True
    assert report["local_browser_render_defaults"]["flaresolverr_port_available"] is True
    assert report["local_browser_render_defaults"]["applied_env_keys"] == [
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    ]
    assert report["local_dependency_wait"]["flaresolverr"] is True
