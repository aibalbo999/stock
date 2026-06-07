from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.start_system import (
    apply_local_dependency_env_defaults,
    dependency_wait_status_lines,
    docker_compose_command,
    ensure_background_process,
    fallback_local_browser_render_to_playwright,
    print_upgrade_capability_preflight,
    pull_missing_dependency_images,
    run_startup_migrations,
    start_dependency_services,
    startup_database_init_mode,
    upgrade_dependency_advice,
    wait_for_local_dependency_ports,
)


def _ready_upgrade_matrix(overrides: dict | None = None) -> dict:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "hybrid_search": {"status": "ready", "evidence": {}},
            "reranking": {"status": "ready", "evidence": {}},
            "llm_observability": {"status": "ready", "evidence": {}},
            "visual_rag": {"status": "ready", "evidence": {}},
            "graphrag_context": {"status": "ready", "evidence": {}},
            "graphrag_path_reasoning": {"status": "ready", "evidence": {}},
            "graphrag_agentic_cypher": {"status": "ready", "evidence": {}},
            "neo4j_payload_export": {"status": "ready", "evidence": {}},
            "neo4j_import": {"status": "ready", "evidence": {}},
        },
        "architecture": {
            "thin_api_controller": {"status": "ready", "evidence": {}},
            "workflow_orchestration": {"status": "ready", "evidence": {}},
            "streamlit_mpa_background_tasks": {"status": "ready", "evidence": {}},
            "database_migrations": {"status": "ready", "evidence": {"up_to_date": True}},
            "secret_scanning": {"status": "ready", "evidence": {}},
        },
        "data_business_logic": {
            "market_data_cache": {"status": "ready", "evidence": {}},
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
            "latest_report_retention": {"status": "ready", "evidence": {}},
            "company_filing_fetch_hardening": {"status": "ready", "evidence": {}},
            "company_filing_pdf_table_parser_runtime": {"status": "ready", "evidence": {}},
            "company_filing_browser_or_proxy_fallback": {"status": "ready", "evidence": {}},
            "company_filing_structured_api_fallback": {"status": "ready", "evidence": {}},
            "company_filing_cache": {"status": "ready", "evidence": {}},
            "source_quality_weighting": {"status": "ready", "evidence": {}},
        },
    }
    for path, value in (overrides or {}).items():
        area, capability = path.split(".")
        matrix[area][capability] = value
    return matrix


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
    assert any("COMPANY_FILING_VISUAL_RAG_ENABLED" in action for action in actions)
    assert any('.venv/bin/python -m pip install -e ".[visual]"' in action for action in actions)
    assert any("FINMIND_TOKEN" in action and "FUGLE_API_KEY" in action for action in actions)
    assert any("COMPANY_FILING_PROXY_URLS" in action for action in actions)
    assert any("COMPANY_FILING_STRUCTURED_API_PROVIDER" in action and "TEJ" in action for action in actions)
    assert any('.venv/bin/python -m pip install -e ".[browser]"' in action for action in actions)
    assert ".venv/bin/python -m alembic stamp head" in actions


def test_start_dependencies_help_mentions_browserless() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/start_system.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    help_text = " ".join(completed.stdout.split())
    assert "Redis, Postgres, Neo4j, and Browserless" in help_text
    assert "--pull-missing-dependencies" in help_text


def test_run_startup_migrations_runs_alembic_upgrade(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setenv("DATABASE_INIT_MODE", "alembic")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = run_startup_migrations(tmp_path, Path("/venv/bin/python"))

    assert result == {"status": "完成", "message": "已執行 alembic upgrade head。"}
    assert captured["command"] == ["/venv/bin/python", "-m", "alembic", "upgrade", "head"]
    assert captured["cwd"] == tmp_path


def test_run_startup_migrations_respects_skip_and_non_alembic_modes(monkeypatch, tmp_path) -> None:
    assert run_startup_migrations(tmp_path, Path("/venv/bin/python"), skip=True)["status"] == "略過"

    monkeypatch.setenv("DATABASE_INIT_MODE", "none")
    assert run_startup_migrations(tmp_path, Path("/venv/bin/python"))["status"] == "略過"

    monkeypatch.setenv("DATABASE_INIT_MODE", "create_all")
    result = run_startup_migrations(tmp_path, Path("/venv/bin/python"))
    assert result["status"] == "略過"
    assert "create_all" in result["message"]


def test_run_startup_migrations_reports_alembic_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_INIT_MODE", "alembic")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="db unavailable\nlast line")

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = run_startup_migrations(tmp_path, Path("/venv/bin/python"))

    assert result == {"status": "失敗", "message": "last line"}


def test_startup_database_init_mode_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_INIT_MODE", "none")

    assert startup_database_init_mode() == "none"


def test_ensure_background_process_skips_running_pid(monkeypatch, tmp_path) -> None:
    (tmp_path / "celery.pid").write_text("123", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.RUN_DIR", tmp_path)
    monkeypatch.setattr("scripts.start_system.is_process_running", lambda pid: pid == 123)

    started = ensure_background_process("celery", ["python", "-m", "celery"], tmp_path / "celery.log")

    assert started is False


def test_ensure_background_process_starts_and_writes_pid(monkeypatch, tmp_path) -> None:
    class FakeProcess:
        pid = 456

    monkeypatch.setattr("scripts.start_system.RUN_DIR", tmp_path)
    monkeypatch.setattr("scripts.start_system.ROOT", tmp_path)
    monkeypatch.setattr("scripts.start_system.is_process_running", lambda _pid: False)
    monkeypatch.setattr("scripts.start_system.subprocess.Popen", lambda *args, **kwargs: FakeProcess())

    started = ensure_background_process("celery", ["python", "-m", "celery"], tmp_path / "celery.log")

    assert started is True
    assert (tmp_path / "celery.pid").read_text(encoding="utf-8") == "456"


def test_apply_local_dependency_env_defaults_supplies_neo4j_for_one_click_start(monkeypatch) -> None:
    for key in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.delenv(key, raising=False)

    applied = apply_local_dependency_env_defaults()

    assert applied == {
        "NEO4J_URI": "neo4j://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "stock_ai_neo4j_password",
        "NEO4J_DATABASE": "neo4j",
    }


def test_apply_local_dependency_env_defaults_preserves_existing_neo4j_env(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "neo4j://custom:7687")
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)

    applied = apply_local_dependency_env_defaults()

    assert "NEO4J_URI" not in applied
    assert applied["NEO4J_USER"] == "neo4j"
    assert applied["NEO4J_PASSWORD"] == "stock_ai_neo4j_password"
    assert applied["NEO4J_DATABASE"] == "neo4j"


def test_apply_local_dependency_env_defaults_can_enable_browser_render_when_available(monkeypatch) -> None:
    for key in (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "scripts.start_system.company_filing_playwright_browser_status",
        lambda: {"browser_available": True},
    )
    monkeypatch.setattr("scripts.start_system.is_port_open", lambda *_args, **_kwargs: False)

    applied = apply_local_dependency_env_defaults(enable_browser_render=True)

    assert applied["COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"] == "true"
    assert applied["NEO4J_URI"] == "neo4j://localhost:7687"
    assert applied["NEO4J_PASSWORD"] == "stock_ai_neo4j_password"
    os.environ.pop("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", None)


def test_apply_local_dependency_env_defaults_prefers_browserless_when_starting_compose(monkeypatch) -> None:
    for key in (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "scripts.start_system.company_filing_playwright_browser_status",
        lambda: {"browser_available": True},
    )

    applied = apply_local_dependency_env_defaults(
        enable_browser_render=True,
        prefer_browserless=True,
    )

    assert applied["COMPANY_FILING_BROWSER_RENDER_ENABLED"] == "true"
    assert applied["COMPANY_FILING_BROWSER_RENDER_URL"].startswith("http://127.0.0.1:3000/content")
    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" not in applied
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_ENABLED", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_URL", None)


def test_apply_local_dependency_env_defaults_skips_browser_render_without_dependency(monkeypatch) -> None:
    for key in (
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "scripts.start_system.company_filing_playwright_browser_status",
        lambda: {"browser_available": False, "fallback_reason": "missing_browser_binary:chromium"},
    )
    monkeypatch.setattr("scripts.start_system.is_port_open", lambda *_args, **_kwargs: False)

    applied = apply_local_dependency_env_defaults(enable_browser_render=True)

    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" not in applied
    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" not in os.environ


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

    assert advice == [
        {
            "capability": "neo4j_import",
            "status": "not_configured",
            "reason": "missing_settings:neo4j_uri",
            "action": (
                "設定 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD；"
                "本機可先執行 docker compose up -d neo4j，或用 start_system.py --start-dependencies"
            ),
        }
    ]


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

    assert advice == [
        {
            "capability": "neo4j_import",
            "status": "degraded",
            "reason": "connection_failed:neo4j",
            "action": (
                "Neo4j 已設定但連線失敗；確認帳密、7687 連線埠與服務狀態。"
                "本機可先執行 docker compose up -d neo4j，或用 start_system.py --start-dependencies"
            ),
        }
    ]


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


def test_upgrade_preflight_uses_audit_and_keeps_optional_neo4j_as_warning(monkeypatch, capsys) -> None:
    class FakeServiceStatusModule:
        @staticmethod
        def service_status() -> dict:
            return {
                "upgrade_capability_matrix": _ready_upgrade_matrix(
                    {
                        "ai_rag.neo4j_import": {
                            "status": "degraded",
                            "evidence": {
                                "fallback_reason": "missing_settings:neo4j_uri",
                                "dependency_available": True,
                            },
                        }
                    }
                )
            }

    monkeypatch.setattr("scripts.start_system.importlib.import_module", lambda _name: FakeServiceStatusModule)

    print_upgrade_capability_preflight(
        Path("/repo"),
        Path("/repo/.venv/bin/python"),
        strict_external=False,
    )

    output = capsys.readouterr().out
    assert "稽核模式：一般" in output
    assert "狀態 caution" in output
    assert "核心升級 ready" in output
    assert "外部整合 caution" in output
    assert "選配或部署注意" in output
    assert "neo4j_import" in output
    assert "必須處理" not in output


def test_upgrade_preflight_strict_mode_requires_external_neo4j(monkeypatch, capsys) -> None:
    class FakeServiceStatusModule:
        @staticmethod
        def service_status() -> dict:
            return {
                "upgrade_capability_matrix": _ready_upgrade_matrix(
                    {
                        "ai_rag.neo4j_import": {
                            "status": "degraded",
                            "evidence": {
                                "fallback_reason": "missing_settings:neo4j_uri",
                                "dependency_available": True,
                            },
                        }
                    }
                )
            }

    monkeypatch.setattr("scripts.start_system.importlib.import_module", lambda _name: FakeServiceStatusModule)

    print_upgrade_capability_preflight(
        Path("/repo"),
        Path("/repo/.venv/bin/python"),
        strict_external=True,
    )

    output = capsys.readouterr().out
    assert "稽核模式：正式部署" in output
    assert "狀態 failed" in output
    assert "核心升級 ready" in output
    assert "外部整合 failed" in output
    assert "必須處理" in output
    assert "neo4j_import" in output


def test_wait_for_local_dependency_ports_waits_for_neo4j_after_compose_start(monkeypatch) -> None:
    captured = {}

    def fake_wait_for_port(host: str, port: int, timeout_seconds: int) -> bool:
        captured["host"] = host
        captured["port"] = port
        captured["timeout_seconds"] = timeout_seconds
        return True

    monkeypatch.setattr("scripts.start_system.wait_for_port", fake_wait_for_port)

    result = wait_for_local_dependency_ports(
        {"status": "已啟動", "message": "ok"},
        {"NEO4J_URI": "neo4j://localhost:7687"},
        timeout_seconds=3,
    )

    assert result == {"neo4j": True}
    assert captured == {"host": "127.0.0.1", "port": 7687, "timeout_seconds": 3}


def test_wait_for_local_dependency_ports_waits_for_browserless_after_compose_start(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("NEO4J_URI", raising=False)

    def fake_wait_for_port(host: str, port: int, timeout_seconds: int) -> bool:
        calls.append((host, port, timeout_seconds))
        return port == 3000

    monkeypatch.setattr("scripts.start_system.wait_for_port", fake_wait_for_port)

    result = wait_for_local_dependency_ports(
        {"status": "已啟動", "message": "ok"},
        {"COMPANY_FILING_BROWSER_RENDER_URL": "http://127.0.0.1:3000/content?token=x"},
        timeout_seconds=4,
    )

    assert result == {"browserless": True}
    assert calls == [("127.0.0.1", 3000, 4)]


def test_wait_for_local_dependency_ports_skips_when_compose_did_not_start(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.start_system.wait_for_port",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not wait")),
    )

    result = wait_for_local_dependency_ports(
        {"status": "略過", "message": "missing docker"},
        {"NEO4J_URI": "neo4j://localhost:7687"},
        timeout_seconds=3,
    )

    assert result == {}


def test_dependency_wait_status_lines_explain_unready_neo4j() -> None:
    lines = dependency_wait_status_lines({"browserless": False, "neo4j": False})

    assert "- Browserless 3000：尚未就緒" in lines
    assert "- Neo4j 7687：尚未就緒" in lines
    assert "docker compose logs neo4j" in lines[-1]
    assert "docker compose logs browserless" in lines[-1]


def test_dependency_wait_status_lines_show_browser_render_fallback() -> None:
    lines = dependency_wait_status_lines(
        {
            "browserless": False,
            "browser_render_fallback": {
                "status": "switched_to_playwright",
                "reason": "browserless_not_ready",
            },
        }
    )

    assert "- browser_render_fallback：switched_to_playwright" in lines
    assert "- Browserless 3000：尚未就緒" in lines


def test_dependency_wait_status_lines_are_empty_without_wait_status() -> None:
    assert dependency_wait_status_lines({}) == []


def test_browserless_default_falls_back_to_playwright_when_dependency_did_not_start(monkeypatch) -> None:
    for key in (
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    local_env = dict(
        {
            "COMPANY_FILING_BROWSER_RENDER_ENABLED": "true",
            "COMPANY_FILING_BROWSER_RENDER_URL": (
                "http://127.0.0.1:3000/content?token=stock_ai_browserless_token"
            ),
        }
    )
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv(
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "http://127.0.0.1:3000/content?token=stock_ai_browserless_token",
    )
    monkeypatch.setattr(
        "scripts.start_system.company_filing_playwright_browser_status",
        lambda: {"browser": "chromium", "browser_available": True},
    )

    result = fallback_local_browser_render_to_playwright(
        local_env,
        {"status": "需下載", "message": "missing browserless image"},
        {},
    )

    assert result["status"] == "switched_to_playwright"
    assert local_env == {"COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED": "true"}
    assert os.environ["COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"] == "true"
    assert "COMPANY_FILING_BROWSER_RENDER_ENABLED" not in os.environ
    assert "COMPANY_FILING_BROWSER_RENDER_URL" not in os.environ
    os.environ.pop("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", None)


def test_browserless_default_stays_when_browserless_is_ready(monkeypatch) -> None:
    local_env = {
        "COMPANY_FILING_BROWSER_RENDER_ENABLED": "true",
        "COMPANY_FILING_BROWSER_RENDER_URL": (
            "http://127.0.0.1:3000/content?token=stock_ai_browserless_token"
        ),
    }
    monkeypatch.setattr(
        "scripts.start_system.company_filing_playwright_browser_status",
        lambda: (_ for _ in ()).throw(AssertionError("should not inspect playwright")),
    )

    result = fallback_local_browser_render_to_playwright(
        local_env,
        {"status": "已啟動", "message": "ok"},
        {"browserless": True},
    )

    assert result == {}
    assert "COMPANY_FILING_BROWSER_RENDER_URL" in local_env


def test_docker_compose_command_prefers_docker_compose_plugin(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "Docker Compose", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    assert docker_compose_command() == ["docker", "compose"]
    assert calls == [["docker", "compose", "version"]]


def test_docker_compose_command_falls_back_to_legacy_binary(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type(
            "Result",
            (),
            {
                "returncode": 1 if command[:2] == ["docker", "compose"] else 0,
                "stdout": "",
                "stderr": "",
            },
        )()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    assert docker_compose_command() == ["docker-compose"]
    assert calls == [["docker", "compose", "version"], ["docker-compose", "version"]]


def test_start_dependency_services_runs_compose_for_required_services(monkeypatch, tmp_path) -> None:
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda: {"all_present": True, "missing_services": [], "remediation": None},
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "已啟動"
    assert captured["cwd"] == tmp_path
    assert captured["command"][-4:] == ["redis", "postgres", "neo4j", "browserless"]


def test_start_dependency_services_explains_missing_images_before_compose_pull(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda: {
            "all_present": False,
            "missing_services": ["neo4j", "browserless"],
            "remediation": "docker compose pull neo4j browserless",
        },
    )

    def fake_run(command, **kwargs):
        raise AssertionError("compose up should wait until user allows missing image pull")

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "需下載"
    assert "缺少 Docker image：neo4j、browserless" in result["message"]
    assert "docker compose pull neo4j browserless" in result["message"]
    assert "--pull-missing-dependencies" in result["message"]


def test_start_dependency_services_can_pull_missing_images_when_explicitly_allowed(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    image_statuses = iter(
        [
            {
                "all_present": False,
                "missing_services": ["neo4j"],
                "remediation": "docker compose pull neo4j",
            },
            {"all_present": True, "missing_services": [], "remediation": None},
        ]
    )
    monkeypatch.setattr("scripts.start_system.local_docker_image_status", lambda: next(image_statuses))

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path, allow_pull_missing_images=True)

    assert result["status"] == "已啟動"
    assert calls[0][-2:] == ["pull", "neo4j"]
    assert calls[1][-4:] == ["redis", "postgres", "neo4j", "browserless"]


def test_start_dependency_services_reports_missing_image_after_pull(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda: {
            "all_present": False,
            "missing_services": ["neo4j"],
            "remediation": "docker compose pull neo4j",
        },
    )

    def fake_run(command, **kwargs):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path, allow_pull_missing_images=True)

    assert result["status"] == "失敗"
    assert "下載後仍缺少：neo4j" in result["message"]


def test_pull_missing_dependency_images_reports_service_timeout(monkeypatch, tmp_path) -> None:
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = pull_missing_dependency_images(
        tmp_path,
        ["docker", "compose"],
        ["neo4j", "browserless"],
        timeout_seconds=30,
    )

    assert result["status"] == "失敗"
    assert "Docker image 下載逾時：neo4j" in result["message"]
    assert "docker compose pull neo4j browserless" in result["message"]


def test_start_dependency_services_explains_image_pull_timeout(monkeypatch, tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(
        "scripts.start_system.local_docker_image_status",
        lambda: {"all_present": True, "missing_services": [], "remediation": None},
    )

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=120)

    monkeypatch.setattr("scripts.start_system.subprocess.run", fake_run)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "失敗"
    assert "docker compose pull neo4j browserless" in result["message"]


def test_start_dependency_services_skips_when_docker_compose_is_missing(monkeypatch, tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr("scripts.start_system.docker_compose_command", lambda: None)

    result = start_dependency_services(tmp_path)

    assert result["status"] == "略過"
    assert "Docker Compose" in result["message"]
