from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.start_system as start_system_module
from app.core.config import get_settings
from scripts.start_system import (
    apply_local_dependency_env_defaults,
    dependency_start_blocker,
    dependency_wait_status_lines,
    ensure_background_process,
    fallback_local_browser_render_to_playwright,
    print_dependency_start_blocker,
    print_upgrade_capability_preflight,
    run_startup_migrations,
    startup_database_init_mode,
    wait_for_local_dependency_ports,
)
from start_system_test_helpers import ready_upgrade_matrix


@pytest.fixture(autouse=True)
def clear_settings_cache_around_start_system_tests():
    env_keys = (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    )
    original_env = {key: os.environ.get(key) for key in env_keys}
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


def test_start_dependencies_help_mentions_browserless() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/start_system.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    help_text = " ".join(completed.stdout.split())
    assert "Redis, Postgres, Neo4j, Browserless, and Chroma" in help_text
    assert "--pull-missing-dependencies" in help_text
    assert "--prefer-unlocker" in help_text


def test_dependency_start_blocker_stops_on_download_or_failure() -> None:
    assert dependency_start_blocker({"status": "需下載", "message": "missing image"})
    assert dependency_start_blocker({"status": "失敗", "message": "compose failed"})
    assert not dependency_start_blocker({"status": "已啟動", "message": "ok"})
    assert not dependency_start_blocker({"status": "略過", "message": "docker compose missing"})
    assert not dependency_start_blocker(None)


def test_print_dependency_start_blocker_explains_next_step(capsys) -> None:
    print_dependency_start_blocker(
        {"status": "需下載", "message": "缺少 Docker image：chroma。"},
        {"chroma": False},
    )

    output = capsys.readouterr().out
    assert "依賴服務：需要先處理" in output
    assert "缺少 Docker image：chroma" in output
    assert "Chroma 8001：尚未就緒" in output
    assert "已停止啟動流程" in output
    assert "migration/API" in output


def test_main_stops_before_migrations_when_dependency_start_needs_download(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr(start_system_module, "ROOT", tmp_path)
    monkeypatch.setattr(start_system_module, "RUN_DIR", tmp_path / ".run")
    monkeypatch.setattr(start_system_module, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(sys, "argv", ["start_system.py", "--start-dependencies"])
    monkeypatch.setattr(start_system_module, "apply_local_dependency_env_defaults", lambda **_kwargs: {})
    monkeypatch.setattr(
        start_system_module,
        "start_dependency_services",
        lambda *_args, **_kwargs: {"status": "需下載", "message": "缺少 Docker image：chroma。"},
    )
    monkeypatch.setattr(start_system_module, "wait_for_local_dependency_ports", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(start_system_module, "fallback_local_browser_render_to_playwright", lambda *_args: {})

    def fail_if_migrations_run(*_args, **_kwargs):
        raise AssertionError("migrations should not run when dependency startup is blocked")

    monkeypatch.setattr(start_system_module, "run_startup_migrations", fail_if_migrations_run)

    assert start_system_module.main() == 1
    assert "已停止啟動流程" in capsys.readouterr().out


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


def test_apply_local_dependency_env_defaults_can_enable_local_chroma(monkeypatch) -> None:
    for key in ("USE_CHROMA", "CHROMA_API_URL"):
        monkeypatch.delenv(key, raising=False)

    applied = apply_local_dependency_env_defaults(enable_chroma=True)

    assert applied["USE_CHROMA"] == "true"
    assert applied["CHROMA_API_URL"] == "http://127.0.0.1:8001"
    os.environ.pop("USE_CHROMA", None)
    os.environ.pop("CHROMA_API_URL", None)


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


def test_apply_local_dependency_env_defaults_can_prefer_flaresolverr_unlocker(monkeypatch) -> None:
    for key in (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    applied = apply_local_dependency_env_defaults(
        enable_browser_render=True,
        prefer_browserless=True,
        prefer_unlocker=True,
    )

    assert applied["COMPANY_FILING_BROWSER_RENDER_ENABLED"] == "true"
    assert applied["COMPANY_FILING_BROWSER_RENDER_PROVIDER"] == "flaresolverr"
    assert applied["COMPANY_FILING_BROWSER_RENDER_URL"] == "http://127.0.0.1:8191/v1"
    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" not in applied
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_ENABLED", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_PROVIDER", None)
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


def test_upgrade_preflight_uses_audit_and_keeps_optional_neo4j_as_warning(monkeypatch, capsys) -> None:
    class FakeServiceStatusModule:
        @staticmethod
        def service_status() -> dict:
            return {
                "upgrade_capability_matrix": ready_upgrade_matrix(
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
    assert "狀態 ready" in output
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
                "upgrade_capability_matrix": ready_upgrade_matrix(
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

    def fake_wait_for_http_ok(url: str, timeout_seconds: int) -> bool:
        calls.append((url, timeout_seconds))
        return "json/version?token=x" in url

    monkeypatch.setattr("scripts.start_system.wait_for_http_ok", fake_wait_for_http_ok)

    result = wait_for_local_dependency_ports(
        {"status": "已啟動", "message": "ok"},
        {"COMPANY_FILING_BROWSER_RENDER_URL": "http://127.0.0.1:3000/content?token=x"},
        timeout_seconds=4,
    )

    assert result == {"browserless": True}
    assert calls == [("http://127.0.0.1:3000/json/version?token=x", 4)]


def test_wait_for_local_dependency_ports_waits_for_flaresolverr_unlocker(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("NEO4J_URI", raising=False)

    def fake_wait_for_http_ok(url: str, timeout_seconds: int) -> bool:
        calls.append((url, timeout_seconds))
        return url == "http://127.0.0.1:8191/health"

    monkeypatch.setattr("scripts.start_system.wait_for_http_ok", fake_wait_for_http_ok)

    result = wait_for_local_dependency_ports(
        {"status": "已啟動", "message": "ok", "services": ["browserless", "flaresolverr"]},
        {"COMPANY_FILING_BROWSER_RENDER_URL": "http://127.0.0.1:8191/v1"},
        timeout_seconds=4,
    )

    assert result == {"browserless": False, "flaresolverr": True}
    assert calls == [
        ("http://127.0.0.1:3000/json/version?token=stock_ai_browserless_token", 4),
        ("http://127.0.0.1:8191/health", 4),
    ]


def test_wait_for_local_dependency_ports_waits_for_core_data_services(monkeypatch) -> None:
    port_calls = []
    http_calls = []
    monkeypatch.delenv("NEO4J_URI", raising=False)

    def fake_wait_for_port(host: str, port: int, timeout_seconds: int) -> bool:
        port_calls.append((host, port, timeout_seconds))
        return port == 6379

    def fake_wait_for_http_ok(url: str, timeout_seconds: int) -> bool:
        http_calls.append((url, timeout_seconds))
        return url == "http://127.0.0.1:8001/api/v2/heartbeat"

    monkeypatch.setattr("scripts.start_system.wait_for_port", fake_wait_for_port)
    monkeypatch.setattr("scripts.start_system.wait_for_http_ok", fake_wait_for_http_ok)

    result = wait_for_local_dependency_ports(
        {"status": "已啟動", "message": "ok", "services": ["redis", "postgres", "chroma"]},
        {"CHROMA_API_URL": "http://127.0.0.1:8001"},
        timeout_seconds=5,
    )

    assert result == {"redis": True, "postgres": False, "chroma": True}
    assert port_calls == [
        ("127.0.0.1", 6379, 5),
        ("127.0.0.1", 5432, 5),
    ]
    assert http_calls == [("http://127.0.0.1:8001/api/v2/heartbeat", 5)]


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


def test_dependency_wait_status_lines_explain_unready_dependencies() -> None:
    lines = dependency_wait_status_lines(
        {
            "browserless": False,
            "chroma": False,
            "flaresolverr": False,
            "neo4j": False,
            "postgres": False,
            "redis": False,
        }
    )

    assert "- Browserless 3000：尚未就緒" in lines
    assert "- Chroma 8001：尚未就緒" in lines
    assert "- FlareSolverr 8191：尚未就緒" in lines
    assert "- Neo4j 7687：尚未就緒" in lines
    assert "- Postgres 5432：尚未就緒" in lines
    assert "- Redis 6379：尚未就緒" in lines
    assert "docker compose logs redis" in lines[-1]
    assert "docker compose logs postgres" in lines[-1]
    assert "docker compose logs neo4j" in lines[-1]
    assert "docker compose logs browserless" in lines[-1]
    assert "docker compose logs chroma" in lines[-1]
    assert "docker compose logs flaresolverr" in lines[-1]


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


def test_flaresolverr_default_falls_back_to_browserless_when_unlocker_is_not_ready(monkeypatch) -> None:
    for key in (
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    local_env = {
        "COMPANY_FILING_BROWSER_RENDER_ENABLED": "true",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER": "flaresolverr",
        "COMPANY_FILING_BROWSER_RENDER_URL": "http://127.0.0.1:8191/v1",
    }
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_ENABLED", "true")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "flaresolverr")
    monkeypatch.setenv("COMPANY_FILING_BROWSER_RENDER_URL", "http://127.0.0.1:8191/v1")
    monkeypatch.setattr(
        "scripts.start_system.company_filing_playwright_browser_status",
        lambda: (_ for _ in ()).throw(AssertionError("should prefer ready browserless")),
    )

    result = fallback_local_browser_render_to_playwright(
        local_env,
        {"status": "已啟動", "message": "ok"},
        {"flaresolverr": False, "browserless": True},
    )

    assert result == {
        "status": "switched_to_browserless",
        "reason": "flaresolverr_not_ready",
        "provider": "browserless",
    }
    assert local_env == {
        "COMPANY_FILING_BROWSER_RENDER_ENABLED": "true",
        "COMPANY_FILING_BROWSER_RENDER_URL": (
            "http://127.0.0.1:3000/content?token=stock_ai_browserless_token"
        ),
    }
    assert os.environ["COMPANY_FILING_BROWSER_RENDER_URL"].startswith("http://127.0.0.1:3000/content")
    assert "COMPANY_FILING_BROWSER_RENDER_PROVIDER" not in os.environ
