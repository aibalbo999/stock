from __future__ import annotations

from app.services.upgrade_audit import audit_upgrade_capabilities


def _fake_status(overrides: dict | None = None) -> dict:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "llm_quota_routing": {"status": "ready", "evidence": {}},
            "hybrid_search": {"status": "ready", "evidence": {}},
            "reranking": {"status": "ready", "evidence": {}},
            "llm_observability": {"status": "ready", "evidence": {}},
            "visual_rag": {"status": "ready", "evidence": {}},
            "graphrag_context": {"status": "ready", "evidence": {}},
            "graphrag_path_reasoning": {"status": "ready", "evidence": {}},
            "graphrag_agentic_cypher": {"status": "ready", "evidence": {}},
            "neo4j_payload_export": {"status": "ready", "evidence": {}},
            "neo4j_import": {"status": "degraded", "evidence": {"fallback_reason": "missing_settings:neo4j_uri"}},
            "graphrag_live_cypher_query": {"status": "ready", "evidence": {}},
        },
        "architecture": {
            "thin_api_controller": {"status": "ready", "evidence": {}},
            "workflow_orchestration": {"status": "ready", "evidence": {}},
            "streamlit_mpa_background_tasks": {"status": "ready", "evidence": {}},
            "background_task_queue": {"status": "ready", "evidence": {}},
            "python_runtime": {"status": "ready", "evidence": {}},
            "database_migrations": {"status": "ready", "evidence": {}},
            "secret_scanning": {"status": "ready", "evidence": {}},
        },
        "data_business_logic": {
            "market_data_cache": {"status": "ready", "evidence": {}},
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
            "latest_report_retention": {"status": "ready", "evidence": {}},
            "company_filing_fetch_hardening": {"status": "ready", "evidence": {}},
            "company_filing_render_provider_contract": {"status": "ready", "evidence": {}},
            "company_filing_pdf_table_parser_runtime": {"status": "ready", "evidence": {}},
            "company_filing_browser_or_proxy_fallback": {"status": "ready", "evidence": {}},
            "company_filing_high_risk_unlocker": {"status": "ready", "evidence": {}},
            "company_filing_structured_api_fallback": {"status": "ready", "evidence": {}},
            "company_filing_cache": {"status": "ready", "evidence": {}},
            "source_quality_weighting": {"status": "ready", "evidence": {}},
        },
    }
    for path, value in (overrides or {}).items():
        area, capability = path.split(".")
        matrix[area][capability] = value
    return {"upgrade_capability_matrix": matrix}


def test_upgrade_audit_treats_live_neo4j_import_as_optional_by_default() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "ai_rag.neo4j_import": {
                    "status": "degraded",
                    "evidence": {
                        "fallback_reason": "missing_settings:neo4j_uri",
                        "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
                        "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
                        "import_smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --json",
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "caution"
    assert audit["summary"]["implementation_status"] == "ready"
    assert audit["summary"]["deployment_status"] == "caution"
    assert audit["summary"]["failures"] == 0
    assert audit["summary"]["warnings"] == 0
    assert audit["summary"]["optional_warnings"] == 1
    assert audit["summary"]["total_warnings"] == 1
    assert audit["warnings"] == []
    warning = audit["optional_warnings"][0]
    assert warning["capability"] == "neo4j_import"
    assert warning["optional"] is True
    assert warning["external_integration"] is True
    assert "scripts.import_supply_chain_graph_neo4j --dry-run" in warning["remediation"]
    assert "neo4j_graphrag_smoke.py --json" in warning["remediation"]
    assert "--import-first" in warning["remediation"]


def test_upgrade_audit_can_require_external_integrations_in_strict_mode() -> None:
    audit = audit_upgrade_capabilities(_fake_status(), strict_external=True)

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "failed"
    assert audit["summary"]["failures"] == 1
    assert audit["failures"][0]["capability"] == "neo4j_import"
    assert audit["failures"][0]["optional"] is False
    assert audit["failures"][0]["external_integration"] is True


def test_upgrade_audit_treats_live_cypher_query_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "ai_rag.graphrag_live_cypher_query": {
                    "status": "degraded",
                    "evidence": {
                        "neo4j_ready": False,
                        "planner_enabled": True,
                        "endpoint": "GET /supply-chain/graph/cypher-query",
                        "payload_dry_run_cli": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
                        "smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --json",
                        "import_smoke_cli": ".venv/bin/python scripts/neo4j_graphrag_smoke.py --import-first --json",
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["implementation"]["status"] == "ready"
    warning = next(
        item for item in audit["optional_warnings"] if item["capability"] == "graphrag_live_cypher_query"
    )
    assert warning["optional"] is True
    assert warning["external_integration"] is True
    assert warning["deployment_check"] is True
    assert "GET /supply-chain/graph/cypher-query" in warning["remediation"]
    assert "scripts.import_supply_chain_graph_neo4j --dry-run" in warning["remediation"]
    assert "neo4j_graphrag_smoke.py --json" in warning["remediation"]
    assert "neo4j_graphrag_smoke.py --import-first --json" in warning["remediation"]


def test_upgrade_audit_treats_company_filing_render_fallback_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_browser_or_proxy_fallback": {
                    "status": "not_configured",
                    "evidence": {
                        "browser_or_proxy_fallback_configured": False,
                        "browser_render_runtime": {
                            "smoke_cli": ".venv/bin/python scripts/company_filing_render_smoke.py --json"
                        },
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "caution"
    warning = next(
        item
        for item in audit["optional_warnings"]
        if item["capability"] == "company_filing_browser_or_proxy_fallback"
    )
    assert warning["capability"] == "company_filing_browser_or_proxy_fallback"
    assert warning["optional"] is True
    assert warning["external_integration"] is True
    assert "company_filing_render_smoke.py --json" in warning["remediation"]


def test_upgrade_audit_treats_high_risk_filing_unlocker_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_high_risk_unlocker": {
                    "status": "not_configured",
                    "evidence": {
                        "configured_provider": "browserless",
                        "provider_tier": "browser_render",
                        "recommended_env": [
                            f"{key}={value}"
                            for key, value in (
                                ("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "flaresolverr"),
                                ("COMPANY_FILING_BROWSER_RENDER_URL", "http://127.0.0.1:8191/v1"),
                            )
                        ],
                        "smoke_cli": (
                            ".venv/bin/python scripts/company_filing_render_smoke.py "
                            "--url https://mops.twse.com.tw/ --json"
                        ),
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "caution"
    warning = next(
        item
        for item in audit["optional_warnings"]
        if item["capability"] == "company_filing_high_risk_unlocker"
    )
    assert warning["optional"] is True
    assert warning["external_integration"] is True
    assert warning["deployment_check"] is True
    assert "FlareSolverr" in warning["remediation"]
    expected_provider_env = "COMPANY_FILING_BROWSER_RENDER_PROVIDER" + "=flaresolverr"
    assert expected_provider_env in warning["remediation"]
    assert "https://mops.twse.com.tw/" in warning["remediation"]


def test_upgrade_audit_treats_structured_filing_api_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_structured_api_fallback": {
                    "status": "not_configured",
                    "evidence": {
                        "configured": False,
                        "runtime": {
                            "sample_contract_cli": (
                                ".venv/bin/python scripts/structured_company_filing_smoke.py "
                                "--sample-json examples/structured_company_filing_sample.json --json"
                            ),
                            "smoke_cli": (
                                ".venv/bin/python scripts/structured_company_filing_smoke.py --json"
                            ),
                        },
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["implementation"]["status"] == "ready"
    warning = next(
        item
        for item in audit["optional_warnings"]
        if item["capability"] == "company_filing_structured_api_fallback"
    )
    assert warning["optional"] is True
    assert warning["external_integration"] is True
    assert "structured_company_filing_sample.json" in warning["remediation"]
    assert "structured_company_filing_smoke.py --json" in warning["remediation"]


def test_upgrade_audit_treats_visual_rag_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "ai_rag.visual_rag": {
                    "status": "not_configured",
                    "evidence": {"enabled": False},
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["implementation"]["status"] == "ready"
    warning = next(item for item in audit["optional_warnings"] if item["capability"] == "visual_rag")
    assert warning["optional"] is True
    assert warning["external_integration"] is True


def test_upgrade_audit_treats_pdf_table_parser_runtime_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_pdf_table_parser_runtime": {
                    "status": "not_configured",
                    "evidence": {
                        "pdf_extract_tables": True,
                        "pdf_table_parser_available": False,
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    warning = next(
        item
        for item in audit["optional_warnings"]
        if item["capability"] == "company_filing_pdf_table_parser_runtime"
    )
    assert warning["optional"] is True
    assert warning["external_integration"] is True


def test_upgrade_audit_treats_python_runtime_as_deployment_preflight() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "architecture.python_runtime": {
                    "status": "degraded",
                    "evidence": {
                        "current_version": "3.9.6",
                        "minimum_supported": "3.11",
                        "current_runtime_supported": False,
                        "bootstrap_dry_run_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --json",
                        "bootstrap_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --apply --replace-existing",
                        "interpreter_install_hints": [
                            {
                                "tool": "homebrew",
                                "command": "brew install python@3.11",
                                "venv_command": "python3.11 -m venv .venv",
                            }
                        ],
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "caution"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "caution"
    warning = next(item for item in audit["warnings"] if item["capability"] == "python_runtime")
    assert warning["optional"] is True
    assert warning["deployment_check"] is True
    assert warning["external_integration"] is False
    assert "brew install python@3.11" in warning["remediation"]
    assert "scripts/bootstrap_python_runtime.py --json" in warning["remediation"]


def test_upgrade_audit_fails_required_capability_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status({"ai_rag.reranking": {"status": "degraded", "evidence": {"fallback_reason": "keyword"}}})
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    assert audit["deployment"]["status"] == "caution"
    assert any(check["capability"] == "reranking" for check in audit["failures"])
    assert audit["areas"]["ai_rag"]["failures"] == 1


def test_upgrade_audit_fails_llm_quota_routing_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "ai_rag.llm_quota_routing": {
                    "status": "degraded",
                    "evidence": {
                        "failed_checks": [
                            "smart_model_order",
                            "flash_models_share_request_budget",
                        ]
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    failure = next(item for item in audit["failures"] if item["capability"] == "llm_quota_routing")
    assert failure["optional"] is False
    assert failure["external_integration"] is False
    assert audit["areas"]["ai_rag"]["failures"] == 1


def test_upgrade_audit_fails_render_provider_contract_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_render_provider_contract": {
                    "status": "degraded",
                    "evidence": {"smoke_cli": "render contract smoke"},
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    failure = next(
        item
        for item in audit["failures"]
        if item["capability"] == "company_filing_render_provider_contract"
    )
    assert failure["optional"] is False
    assert failure["external_integration"] is False
    assert failure["deployment_check"] is False


def test_upgrade_audit_fails_frontend_blocking_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "architecture.streamlit_mpa_background_tasks": {
                    "status": "degraded",
                    "evidence": {"asyncio_run_count": 1, "long_blocking_post_timeout_present": True},
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    assert any(check["capability"] == "streamlit_mpa_background_tasks" for check in audit["failures"])
    assert audit["areas"]["architecture"]["failures"] == 1


def test_upgrade_audit_fails_background_task_queue_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "architecture.background_task_queue": {
                    "status": "degraded",
                    "evidence": {
                        "broker_ok": False,
                        "submission_contract_ready": True,
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    failure = next(item for item in audit["failures"] if item["capability"] == "background_task_queue")
    assert failure["optional"] is False
    assert failure["evidence"]["broker_ok"] is False
    assert audit["areas"]["architecture"]["failures"] == 1


def test_upgrade_audit_fails_report_retention_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.latest_report_retention": {
                    "status": "degraded",
                    "evidence": {"write_prunes_db_by_topic": False},
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    assert any(check["capability"] == "latest_report_retention" for check in audit["failures"])
    assert audit["areas"]["data_business_logic"]["failures"] == 1
