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
            "neo4j_import": {
                "status": "degraded",
                "evidence": {"fallback_reason": "missing_settings:neo4j_uri"},
            },
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
            "company_filing_official_material_information_openapi": {
                "status": "ready",
                "evidence": {},
            },
            "company_filing_structured_api_fallback": {"status": "ready", "evidence": {}},
            "company_filing_structured_api_sample_contract": {"status": "ready", "evidence": {}},
            "company_filing_cache": {"status": "ready", "evidence": {}},
            "source_quality_weighting": {"status": "ready", "evidence": {}},
        },
    }
    for path, value in (overrides or {}).items():
        area, capability = path.split(".")
        matrix[area][capability] = value
    return {
        "upgrade_capability_matrix": matrix,
        "local_dependencies": {
            "collector_path": "app/services/local_dependency_diagnostics.py",
            "status": "partial",
            "open_services": ["redis"],
            "missing_core_services": ["neo4j"],
            "ports": [
                {
                    "service": "redis",
                    "label": "Redis",
                    "host": "127.0.0.1",
                    "port": 6379,
                    "open": True,
                    "role": "Celery broker/backend 與快取",
                }
            ],
            "commands": {
                "start_core": ".venv/bin/python scripts/start_system.py --start-dependencies",
                "verify_neo4j": (
                    ".venv/bin/python scripts/upgrade_audit.py "
                    "--local-neo4j-defaults --wait-local-neo4j 20 --json"
                ),
            },
        },
        "local_dependency_auto_defaults": {
            "mode": "status_preview",
            "detected": {"neo4j": False},
            "capability_matches": [],
        },
    }


def test_upgrade_audit_includes_local_dependency_runtime_status() -> None:
    audit = audit_upgrade_capabilities(_fake_status())

    assert audit["local_dependencies"]["collector_path"] == (
        "app/services/local_dependency_diagnostics.py"
    )
    assert audit["local_dependencies"]["status"] == "partial"
    assert audit["local_dependencies"]["open_services"] == ["redis"]
    assert audit["local_dependencies"]["missing_core_services"] == ["neo4j"]
    assert "start_core" in audit["local_dependencies"]["commands"]
    assert audit["local_dependency_auto_defaults"]["mode"] == "status_preview"


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
    assert audit["deployment"]["blocking_status"] == "ready"
    assert audit["deployment"]["optional_only"] is True
    assert audit["summary"]["implementation_status"] == "ready"
    assert audit["summary"]["deployment_status"] == "caution"
    assert audit["summary"]["deployment_blocking_status"] == "ready"
    assert audit["summary"]["deployment_blocking_warnings"] == 0
    assert audit["summary"]["deployment_blocking_failures"] == 0
    assert audit["summary"]["deployment_optional_only"] is True
    assert audit["summary"]["failures"] == 0
    assert audit["summary"]["warnings"] == 0
    assert audit["summary"]["optional_warnings"] == 1
    assert audit["summary"]["total_warnings"] == 1
    assert audit["warnings"] == []
    assert audit["external_deployment_enablement"]["total"] == 7
    assert audit["external_deployment_enablement"]["pending"] == 1
    assert audit["external_deployment_enablement"]["blocking_pending"] == 0
    assert audit["external_deployment_enablement"]["nonblocking_optional_pending"] == 1
    assert audit["external_deployment_enablement"]["all_pending_optional"] is True
    assert audit["external_deployment_enablement"]["paid_external_only_pending"] is False
    assert audit["external_deployment_enablement"]["free_local_pending"] == 1
    assert audit["external_deployment_enablement"]["local_action_available"] == 1
    assert audit["external_deployment_enablement"]["paid_external_pending"] == 0
    assert audit["external_deployment_enablement"]["primary_next_action"] == (
        "先處理本機免費可補強項目，再評估 API 額度或付費資料商。"
    )
    assert audit["external_deployment_pending_gap_action_counts"] == {
        "local_action": 1,
        "quota_or_external": 0,
        "paid_external": 0,
        "manual_configuration": 0,
    }
    assert audit["external_deployment_pending_gaps"][0]["capability"] == "neo4j_import"
    assert audit["external_deployment_pending_gaps"][0]["action_type"] == "local_action"
    warning = audit["optional_warnings"][0]
    assert warning["capability"] == "neo4j_import"
    assert warning["optional"] is True
    assert warning["external_integration"] is True
    assert warning["enablement_profile"]["deployment_profile"] == "free_local"
    assert warning["enablement_profile"]["group_label"] == "可本機免費啟用"
    assert "scripts.import_supply_chain_graph_neo4j --dry-run" in warning["remediation"]
    assert "neo4j_graphrag_smoke.py --json" in warning["remediation"]
    assert "--import-first" in warning["remediation"]


def test_upgrade_audit_can_require_external_integrations_in_strict_mode() -> None:
    audit = audit_upgrade_capabilities(_fake_status(), strict_external=True)

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "failed"
    assert audit["deployment"]["blocking_status"] == "failed"
    assert audit["deployment"]["optional_only"] is False
    assert audit["summary"]["deployment_optional_only"] is False
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
        item
        for item in audit["optional_warnings"]
        if item["capability"] == "graphrag_live_cypher_query"
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
                            "--local-browser-render-defaults --prefer-unlocker "
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
                            "sample_contract_ready": True,
                            "sample_contract_cli": (
                                ".venv/bin/python scripts/structured_company_filing_smoke.py "
                                "--sample-json examples/structured_company_filing_sample.json --json"
                            ),
                            "local_fixture_start_cli": (
                                ".venv/bin/python scripts/local_structured_company_filing_api.py "
                                "--sample-json examples/structured_company_filing_sample.json"
                            ),
                            "local_fixture_http_smoke_cli": (
                                ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                                "--json --strict"
                            ),
                            "local_fixture_smoke_cli": (
                                "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom "
                                "COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings "
                                ".venv/bin/python scripts/structured_company_filing_smoke.py --json"
                            ),
                            "smoke_cli": (
                                ".venv/bin/python scripts/structured_company_filing_smoke.py --json"
                            ),
                            "free_validation": {
                                "sample_contract_ready": True,
                                "local_fixture_available": True,
                                "local_fixture_start_cli": (
                                    ".venv/bin/python scripts/local_structured_company_filing_api.py "
                                    "--sample-json examples/structured_company_filing_sample.json"
                                ),
                                "local_fixture_http_smoke_cli": (
                                    ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                                    "--json --strict"
                                ),
                                "local_fixture_provider_profile_smoke_cli": (
                                    ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
                                    "--provider-profile tej --json --strict"
                                ),
                                "local_fixture_smoke_cli": (
                                    "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom "
                                    "COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings "
                                    ".venv/bin/python scripts/structured_company_filing_smoke.py --json"
                                ),
                            },
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
    assert warning["enablement_profile"]["deployment_profile"] == "paid_external"
    assert warning["enablement_profile"]["paid_service_required"] is True
    assert warning["enablement_profile"]["free_validation_available"] is True
    assert warning["enablement_profile"]["free_validation_label"] == (
        "樣本資料 + 本機測試 API + 提供者設定可驗證"
    )
    assert len(warning["enablement_profile"]["free_validation_commands"]) == 5
    assert "structured_company_filing_sample.json" in warning["remediation"]
    assert "structured_company_filing_fixture_smoke.py" in warning["remediation"]
    assert "--provider-profile tej" in warning["remediation"]
    assert "local_structured_company_filing_api.py" in warning["remediation"]
    assert "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom" in warning["remediation"]
    assert "structured_company_filing_smoke.py --json" in warning["remediation"]
    pending = audit["external_deployment_pending_gaps"][-1]
    assert pending["capability"] == "company_filing_structured_api_fallback"
    assert pending["free_validation_available"] is True
    assert pending["free_validation_label"] == "樣本資料 + 本機測試 API + 提供者設定可驗證"


def test_upgrade_audit_marks_paid_external_only_gaps_as_nonblocking_optional() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "ai_rag.neo4j_import": {"status": "ready", "evidence": {}},
                "data_business_logic.company_filing_structured_api_fallback": {
                    "status": "not_configured",
                    "evidence": {
                        "configured": False,
                        "runtime": {
                            "smoke_cli": (
                                ".venv/bin/python scripts/structured_company_filing_smoke.py --json"
                            ),
                        },
                    },
                },
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["deployment"]["status"] == "caution"
    assert audit["deployment"]["blocking_status"] == "ready"
    assert audit["deployment"]["optional_only"] is True
    assert audit["summary"]["deployment_optional_only"] is True
    assert audit["summary"]["deployment_blocking_status"] == "ready"
    enablement = audit["external_deployment_enablement"]
    assert enablement["pending"] == 1
    assert enablement["blocking_pending"] == 0
    assert enablement["nonblocking_optional_pending"] == 1
    assert enablement["all_pending_optional"] is True
    assert enablement["paid_external_only_pending"] is True
    assert enablement["primary_next_action"] == (
        "剩餘項目都是付費外部 API 或資料商選配；免費版可先維持樣本資料格式檢查。"
    )
    projection = audit["external_deployment_local_projection"]
    assert projection["available_local_default_gap_count"] == 0
    assert projection["remaining_pending"] == 1
    assert projection["remaining_paid_external_pending"] == 1
    assert projection["next_action"] == "目前有效剩餘 1 項付費外部資料 API 選配。"


def test_upgrade_audit_projects_effective_external_gaps_after_local_defaults() -> None:
    status = _fake_status(
        {
            "ai_rag.neo4j_import": {
                "status": "degraded",
                "evidence": {"fallback_reason": "missing_settings:neo4j_uri"},
            },
            "ai_rag.graphrag_live_cypher_query": {
                "status": "degraded",
                "evidence": {"fallback_reason": "missing_settings:neo4j_uri"},
            },
            "data_business_logic.company_filing_high_risk_unlocker": {
                "status": "not_configured",
                "evidence": {},
            },
            "data_business_logic.company_filing_structured_api_fallback": {
                "status": "not_configured",
                "evidence": {},
            },
        }
    )
    status["local_dependency_auto_defaults"] = {
        "mode": "status_preview",
        "capability_matches": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "group": "neo4j",
                "state": "would_apply",
                "would_apply": True,
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
            {
                "area": "ai_rag",
                "capability": "graphrag_live_cypher_query",
                "group": "neo4j",
                "state": "would_apply",
                "would_apply": True,
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "group": "flaresolverr",
                "state": "would_apply",
                "would_apply": True,
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
        ],
    }

    audit = audit_upgrade_capabilities(status)

    projection = audit["external_deployment_local_projection"]
    assert projection["status_after_available_local_defaults"] == "caution"
    assert projection["current_pending"] == 4
    assert projection["current_blocking_pending"] == 0
    assert projection["current_optional_pending"] == 4
    assert projection["available_local_default_gap_count"] == 3
    assert projection["remaining_pending"] == 1
    assert projection["remaining_blocking_pending"] == 0
    assert projection["remaining_optional_pending"] == 1
    assert projection["remaining_paid_external_pending"] == 1
    assert projection["remaining_action_counts"] == {
        "local_action": 0,
        "quota_or_external": 0,
        "paid_external": 1,
        "manual_configuration": 0,
    }
    assert {row["capability"] for row in projection["local_default_capabilities"]} == {
        "neo4j_import",
        "graphrag_live_cypher_query",
        "company_filing_high_risk_unlocker",
    }
    assert projection["remaining_capabilities"] == [
        {
            "area": "data_business_logic",
            "capability": "company_filing_structured_api_fallback",
            "label": "公司文件結構化 API 備援",
            "action_type": "paid_external",
        }
    ]
    assert projection["local_default_verify_commands"] == [
        ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
    ]
    assert "有效剩餘 1 項付費外部資料 API 選配" in projection["next_action"]


def test_upgrade_audit_includes_optimization_progress_for_operator_json() -> None:
    status = _fake_status(
        {
            "ai_rag.neo4j_import": {
                "status": "degraded",
                "evidence": {"fallback_reason": "missing_settings:neo4j_uri"},
            },
            "ai_rag.graphrag_live_cypher_query": {
                "status": "degraded",
                "evidence": {"fallback_reason": "missing_settings:neo4j_uri"},
            },
            "data_business_logic.company_filing_high_risk_unlocker": {
                "status": "not_configured",
                "evidence": {},
            },
            "data_business_logic.company_filing_structured_api_fallback": {
                "status": "not_configured",
                "evidence": {},
            },
        }
    )
    status["local_dependency_auto_defaults"] = {
        "mode": "status_preview",
        "capability_matches": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "group": "neo4j",
                "state": "would_apply",
                "would_apply": True,
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
            {
                "area": "ai_rag",
                "capability": "graphrag_live_cypher_query",
                "group": "neo4j",
                "state": "would_apply",
                "would_apply": True,
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
            {
                "area": "data_business_logic",
                "capability": "company_filing_high_risk_unlocker",
                "group": "flaresolverr",
                "state": "would_apply",
                "would_apply": True,
                "verify_command": ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json",
            },
        ],
    }

    audit = audit_upgrade_capabilities(status)

    progress = audit["optimization_progress"]
    assert progress["status"] == "ready_with_optional_gaps"
    assert progress["blocking_gap_count"] == 0
    assert progress["optional_gap_count"] == 4
    assert progress["local_resolvable_gap_count"] == 3
    assert (
        progress["effective_optional_gap_count_after_available_local_defaults"] == 1
    )
    assert progress["primary_next_action"]["capability"] == "auto_local_defaults"
    assert progress["primary_next_action"]["label"] == "本機 defaults 可驗證"
    assert progress["summary"]["primary_next_action_label"] == "本機 defaults 可驗證"
    assert (
        ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
        in progress["local_default_verify_commands"]
    )
    assert audit["optimization_progress_scope"] == {
        "scope": "optimization_objective",
        "optimization_check_count": 32,
        "audit_check_count": 33,
        "excluded_audit_checks": [
            {
                "area": "architecture",
                "capability": "python_runtime",
                "label": "Python 3.11+ runtime",
            }
        ],
        "note": (
            "Optimization progress tracks the user-approved objective domains; "
            "upgrade audit also includes deployment preflight checks."
        ),
    }


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
    warning = next(
        item for item in audit["optional_warnings"] if item["capability"] == "visual_rag"
    )
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
        _fake_status(
            {"ai_rag.reranking": {"status": "degraded", "evidence": {"fallback_reason": "keyword"}}}
        )
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
                            "official_free_tier_request_budgets_match",
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


def test_upgrade_audit_fails_structured_api_sample_contract_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_structured_api_sample_contract": {
                    "status": "degraded",
                    "evidence": {
                        "smoke_cli": "structured sample data check",
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    failure = next(
        item
        for item in audit["failures"]
        if item["capability"] == "company_filing_structured_api_sample_contract"
    )
    assert failure["optional"] is False
    assert failure["external_integration"] is False
    assert failure["deployment_check"] is False
    assert "structured_company_filing_sample.json" in failure["remediation"]


def test_upgrade_audit_fails_frontend_blocking_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "architecture.streamlit_mpa_background_tasks": {
                    "status": "degraded",
                    "evidence": {
                        "asyncio_run_count": 1,
                        "long_blocking_post_timeout_present": True,
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    assert any(
        check["capability"] == "streamlit_mpa_background_tasks" for check in audit["failures"]
    )
    assert audit["areas"]["architecture"]["failures"] == 1


def test_upgrade_audit_passes_background_task_queue_when_only_live_runtime_is_down() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "architecture.background_task_queue": {
                    "status": "ready",
                    "evidence": {
                        "implementation_ready": True,
                        "runtime_ready": False,
                        "broker_ok": False,
                        "submission_contract_ready": True,
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "ready"
    assert audit["implementation"]["status"] == "ready"
    assert not any(
        item["capability"] == "background_task_queue" for item in audit["failures"]
    )


def test_upgrade_audit_fails_background_task_queue_wiring_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "architecture.background_task_queue": {
                    "status": "degraded",
                    "evidence": {
                        "implementation_ready": False,
                        "runtime_ready": True,
                        "broker_ok": True,
                        "submission_contract_ready": False,
                        "missing_task_exports": ["maintenance_diagnostic_task"],
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    failure = next(
        item for item in audit["failures"] if item["capability"] == "background_task_queue"
    )
    assert failure["optional"] is False
    assert failure["evidence"]["submission_contract_ready"] is False
    assert "maintenance_diagnostic_task" in failure["remediation"]
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
