from __future__ import annotations

from pathlib import Path

from scripts.start_system import upgrade_dependency_advice
from start_system_test_helpers import ready_upgrade_matrix


def test_upgrade_dependency_advice_points_to_missing_rag_and_llm_dependencies() -> None:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {
                "status": "degraded",
                "evidence": {
                    "provider": "sentence_transformers",
                    "fallback_reason": "missing_dependency:sentence_transformers",
                },
            },
            "llm_sdk_and_fallback": {
                "status": "degraded",
                "evidence": {"dependency": "litellm", "dependency_available": False},
            },
            "llm_quota_routing": {
                "status": "degraded",
                "evidence": {
                    "failed_checks": [
                        "smart_model_order",
                        "official_free_tier_request_budgets_match",
                    ]
                },
            },
            "neo4j_import": {
                "status": "not_configured",
                "evidence": {"fallback_reason": "missing_settings:neo4j_uri"},
            },
            "visual_rag": {
                "status": "not_configured",
                "evidence": {
                    "enabled": False,
                    "renderer_dependency_available": False,
                    "runtime": {
                        "fallback_reason": "visual_rag_disabled",
                        "vision_model_key_configured": False,
                    },
                },
            },
        },
        "architecture": {
            "database_migrations": {
                "status": "degraded",
                "evidence": {
                    "up_to_date": False,
                    "version_table_present": False,
                    "head_revision": "0001_initial_schema",
                    "current_revision": None,
                },
            },
        },
        "data_business_logic": {
            "market_data_provider_fallback": {
                "status": "degraded",
                "evidence": {
                    "fallback_reason": (
                        "missing_finmind_token_for_monthly_revenue_financials_valuation;"
                        "missing_fugle_api_key_for_price_fallback"
                    ),
                    "finmind_authenticated": False,
                    "fugle_price_fallback_configured": False,
                },
            },
            "company_filing_browser_or_proxy_fallback": {
                "status": "not_configured",
                "evidence": {"playwright_render_dependency_available": False},
            },
            "company_filing_structured_api_fallback": {
                "status": "not_configured",
                "evidence": {"runtime": {"fallback_reason": "missing_structured_api_provider_or_url"}},
            },
        },
    }

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    actions = [item["action"] for item in advice]
    assert any("pip install --upgrade pip setuptools" in action for action in actions)
    assert any('.venv/bin/python -m pip install -e ".[rag]"' in action for action in actions)
    assert any('.venv/bin/python -m pip install -e "."' in action for action in actions)
    assert any("NEO4J_URI" in action for action in actions)
    assert any("scripts/neo4j_graphrag_smoke.py" in action for action in actions)
    assert any("COMPANY_FILING_VISUAL_RAG_ENABLED" in action for action in actions)
    assert any('.venv/bin/python -m pip install -e ".[visual]"' in action for action in actions)
    assert any("LLM_MODEL_DAILY_REQUEST_BUDGETS" in action and "gemma-4-31b-it" in action for action in actions)
    assert any("FINMIND_TOKEN" in action and "FUGLE_API_KEY" in action for action in actions)
    assert any("COMPANY_FILING_PROXY_URLS" in action for action in actions)
    assert any("scripts/company_filing_render_smoke.py" in action for action in actions)
    assert any("COMPANY_FILING_STRUCTURED_API_PROVIDER" in action and "TEJ" in action for action in actions)
    assert any('.venv/bin/python -m pip install -e ".[browser]"' in action for action in actions)
    assert ".venv/bin/python -m alembic stamp head" in actions


def test_upgrade_dependency_advice_is_empty_when_capabilities_are_ready() -> None:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "neo4j_import": {"status": "ready", "evidence": {}},
        },
        "architecture": {
            "database_migrations": {
                "status": "ready",
                "evidence": {"up_to_date": True},
            },
        },
        "data_business_logic": {
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
        },
    }

    assert upgrade_dependency_advice(matrix, python=Path("/repo/.venv/bin/python"), root=Path("/repo")) == []


def test_upgrade_dependency_advice_skips_graph_install_when_neo4j_driver_is_available() -> None:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "neo4j_import": {
                "status": "not_configured",
                "evidence": {
                    "fallback_reason": "missing_settings:neo4j_uri",
                    "dependency_available": True,
                },
            },
        },
        "architecture": {
            "database_migrations": {"status": "ready", "evidence": {"up_to_date": True}},
        },
        "data_business_logic": {
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
        },
    }

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    assert len(advice) == 1
    assert advice[0]["capability"] == "neo4j_import"
    assert advice[0]["status"] == "not_configured"
    assert advice[0]["reason"] == "missing_settings:neo4j_uri"
    assert "NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD" in advice[0]["action"]
    assert "start_system.py --start-dependencies" in advice[0]["action"]
    assert "scripts/neo4j_graphrag_smoke.py" in advice[0]["action"]


def test_upgrade_dependency_advice_installs_graph_extra_when_neo4j_driver_is_missing() -> None:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "neo4j_import": {
                "status": "not_configured",
                "evidence": {
                    "fallback_reason": "missing_dependency:neo4j",
                    "dependency_available": False,
                },
            },
        },
        "architecture": {
            "database_migrations": {"status": "ready", "evidence": {"up_to_date": True}},
        },
        "data_business_logic": {
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
        },
    }

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    assert len(advice) == 1
    assert '.venv/bin/python -m pip install -e ".[graph]"' in advice[0]["action"]
    assert "NEO4J_URI" in advice[0]["action"]


def test_upgrade_dependency_advice_explains_neo4j_connection_failure() -> None:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "neo4j_import": {
                "status": "degraded",
                "evidence": {
                    "fallback_reason": "connection_failed:neo4j",
                    "dependency_available": True,
                    "configured": True,
                    "connection_checked": True,
                    "connection_ok": False,
                },
            },
        },
        "architecture": {
            "database_migrations": {"status": "ready", "evidence": {"up_to_date": True}},
        },
        "data_business_logic": {
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
        },
    }

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    assert len(advice) == 1
    assert advice[0]["capability"] == "neo4j_import"
    assert advice[0]["status"] == "degraded"
    assert advice[0]["reason"] == "connection_failed:neo4j"
    assert "Neo4j 已設定但連線失敗" in advice[0]["action"]
    assert "start_system.py --start-dependencies" in advice[0]["action"]
    assert "scripts/neo4j_graphrag_smoke.py" in advice[0]["action"]


def test_upgrade_dependency_advice_explains_live_cypher_query_gap() -> None:
    matrix = ready_upgrade_matrix(
        {
            "ai_rag.graphrag_live_cypher_query": {
                "status": "degraded",
                "evidence": {"neo4j_ready": False, "planner_enabled": True},
            }
        }
    )

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    assert len(advice) == 1
    assert advice[0]["capability"] == "graphrag_live_cypher_query"
    assert "Neo4j ready=False" in advice[0]["reason"]
    assert "/supply-chain/graph/cypher-query" in advice[0]["action"]


def test_upgrade_dependency_advice_explains_market_data_provider_gap() -> None:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "neo4j_import": {"status": "ready", "evidence": {}},
        },
        "architecture": {
            "database_migrations": {"status": "ready", "evidence": {"up_to_date": True}},
        },
        "data_business_logic": {
            "market_data_provider_fallback": {
                "status": "degraded",
                "evidence": {
                    "fallback_reason": (
                        "missing_finmind_token_for_monthly_revenue_financials_valuation;"
                        "missing_fugle_api_key_for_price_fallback"
                    ),
                    "finmind_authenticated": False,
                    "fugle_price_fallback_configured": False,
                },
            }
        },
    }

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    assert advice == [
        {
            "capability": "market_data_provider_fallback",
            "status": "degraded",
            "reason": (
                "missing_finmind_token_for_monthly_revenue_financials_valuation;"
                "missing_fugle_api_key_for_price_fallback"
            ),
            "action": (
                "設定 FINMIND_TOKEN，讓月營收、五年財務與估值使用穩定授權來源；"
                "設定 FUGLE_API_KEY，讓股價歷史在 FinMind 失敗時可切到 Fugle"
            ),
        }
    ]


def test_upgrade_dependency_advice_explains_keyword_reranker_gap() -> None:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "reranking": {
                "status": "degraded",
                "evidence": {
                    "provider": "keyword",
                    "execution_mode": "keyword",
                    "available": True,
                    "keyword_fallback": True,
                    "model_reranker_ready": False,
                    "model_reranker_gap": "keyword_provider_selected",
                },
            },
            "neo4j_import": {"status": "ready", "evidence": {}},
        },
        "architecture": {
            "database_migrations": {"status": "ready", "evidence": {"up_to_date": True}},
        },
        "data_business_logic": {
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
        },
    }

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    assert len(advice) == 1
    assert advice[0]["capability"] == "reranking"
    assert advice[0]["reason"] == "keyword execution_mode=keyword（keyword_provider_selected）"
    assert "RAG_RERANKER_PROVIDER=bge" in advice[0]["action"]
    assert "COHERE_API_KEY" in advice[0]["action"]


def test_upgrade_dependency_advice_points_to_python_runtime_mismatch() -> None:
    matrix = ready_upgrade_matrix(
        {
            "architecture.python_runtime": {
                "status": "degraded",
                "evidence": {
                    "current_version": "3.9.6",
                    "minimum_supported": "3.11",
                    "current_runtime_supported": False,
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

    advice = upgrade_dependency_advice(
        matrix,
        python=Path("/repo/.venv/bin/python"),
        root=Path("/repo"),
    )

    assert advice[0]["capability"] == "python_runtime"
    assert "Python 3.9.6" in advice[0]["reason"]
    assert "brew install python@3.11" in advice[0]["action"]
    assert "scripts/bootstrap_python_runtime.py --apply --replace-existing" in advice[0]["action"]
    assert "python3.11 -m venv .venv" in advice[0]["action"]
