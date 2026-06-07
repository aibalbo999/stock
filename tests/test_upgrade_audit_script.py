from __future__ import annotations

import os
import subprocess

from scripts import upgrade_audit


def test_upgrade_audit_script_prints_text_and_returns_success_for_warnings(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        upgrade_audit,
        "audit_upgrade_capabilities",
        lambda strict_external=False: {
            "overall_status": "ready",
            "summary": {
                "ready": 1,
                "warnings": 0,
                "optional_warnings": 1,
                "total_warnings": 1,
                "failures": 0,
            },
            "implementation": {"status": "ready", "ready": 1, "total_checks": 1},
            "deployment": {"status": "caution", "ready": 0, "total_checks": 1},
            "checks": [
                {
                    "severity": "pass",
                    "optional": False,
                    "area": "ai_rag",
                    "capability": "hybrid_search",
                    "label": "Hybrid Search",
                    "status": "ready",
                    "remediation": None,
                },
                {
                    "severity": "warn",
                    "optional": True,
                    "area": "ai_rag",
                    "capability": "neo4j_import",
                    "label": "Neo4j import",
                    "status": "degraded",
                    "remediation": "設定 NEO4J_URI",
                },
            ],
            "failures": [],
            "warnings": [],
            "optional_warnings": [
                {
                    "severity": "warn",
                    "optional": True,
                    "area": "ai_rag",
                    "capability": "neo4j_import",
                    "label": "Neo4j import",
                    "status": "degraded",
                    "remediation": "設定 NEO4J_URI",
                }
            ],
        },
    )

    exit_code = upgrade_audit.main([])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Upgrade audit: ready" in output
    assert "Core implementation: ready (1/1 ready)" in output
    assert "External integrations: caution (0/1 ready)" in output
    assert "Checks: 1 ready, 0 warnings, 1 optional deployment warnings, 0 failures" in output
    assert "[WARN optional] ai_rag.neo4j_import" in output


def test_upgrade_audit_script_returns_failure_when_required_check_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        upgrade_audit,
        "audit_upgrade_capabilities",
        lambda strict_external=False: {
            "overall_status": "failed",
            "summary": {"ready": 0, "warnings": 0, "failures": 1},
            "implementation": {"status": "failed", "ready": 0, "total_checks": 1},
            "deployment": {"status": "ready", "ready": 1, "total_checks": 1},
            "checks": [],
            "failures": [{"capability": "reranking"}],
        },
    )

    assert upgrade_audit.main([]) == 1


def test_upgrade_audit_script_can_apply_local_neo4j_defaults(monkeypatch, capsys) -> None:
    for key in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    captured = {}

    def fake_audit(strict_external=False):
        captured["strict_external"] = strict_external
        captured["neo4j_uri"] = os.environ.get("NEO4J_URI")
        return {
            "overall_status": "caution",
            "summary": {"ready": 14, "warnings": 1, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "caution", "ready": 0, "total_checks": 1},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--local-neo4j-defaults", "--strict-external", "--json"])

    assert exit_code == 0
    assert captured == {"strict_external": True, "neo4j_uri": "neo4j://localhost:7687"}
    output = capsys.readouterr().out
    assert '"local_dependency_defaults"' in output
    assert "NEO4J_PASSWORD" in output
    assert "stock_ai_neo4j_password" not in output


def test_upgrade_audit_script_can_apply_local_browser_render_defaults(monkeypatch, capsys) -> None:
    for key in (
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    monkeypatch.setattr(
        upgrade_audit,
        "company_filing_playwright_browser_status",
        lambda: {"dependency_available": True, "browser_available": True, "fallback_reason": None},
    )
    monkeypatch.setattr(upgrade_audit, "is_port_open", lambda *_args, **_kwargs: False)
    captured = {}

    def fake_audit(strict_external=False):
        captured["playwright_enabled"] = os.environ.get("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED")
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--local-browser-render-defaults", "--json"])

    assert exit_code == 0
    assert captured == {"playwright_enabled": "true"}
    output = capsys.readouterr().out
    assert '"local_browser_render_defaults"' in output
    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" in output
    os.environ.pop("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED", None)


def test_upgrade_audit_script_can_apply_local_browserless_defaults(monkeypatch, capsys) -> None:
    for key in (
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    monkeypatch.setattr(
        upgrade_audit,
        "company_filing_playwright_browser_status",
        lambda: {"dependency_available": False, "browser_available": False},
    )
    monkeypatch.setattr(
        upgrade_audit,
        "is_port_open",
        lambda host, port: (host, port) == ("127.0.0.1", 3000),
    )
    captured = {}

    def fake_audit(strict_external=False):
        captured["browser_render_enabled"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_ENABLED")
        captured["browser_render_url"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_URL")
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--local-browser-render-defaults", "--json"])

    assert exit_code == 0
    assert captured["browser_render_enabled"] == "true"
    assert captured["browser_render_url"].startswith("http://127.0.0.1:3000/content")
    output = capsys.readouterr().out
    assert "COMPANY_FILING_BROWSER_RENDER_URL" in output
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_ENABLED", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_PROVIDER", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_URL", None)


def test_upgrade_audit_script_can_apply_local_flaresolverr_defaults(monkeypatch, capsys) -> None:
    for key in (
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    monkeypatch.setattr(
        upgrade_audit,
        "company_filing_playwright_browser_status",
        lambda: {"dependency_available": False, "browser_available": False},
    )
    monkeypatch.setattr(
        upgrade_audit,
        "is_port_open",
        lambda host, port: (host, port) == ("127.0.0.1", 8191),
    )
    captured = {}

    def fake_audit(strict_external=False):
        captured["browser_render_enabled"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_ENABLED")
        captured["browser_render_provider"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_PROVIDER")
        captured["browser_render_url"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_URL")
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--local-browser-render-defaults", "--prefer-unlocker", "--json"])

    assert exit_code == 0
    assert captured == {
        "browser_render_enabled": "true",
        "browser_render_provider": "flaresolverr",
        "browser_render_url": "http://127.0.0.1:8191/v1",
    }
    output = capsys.readouterr().out
    assert "COMPANY_FILING_BROWSER_RENDER_PROVIDER" in output
    assert '"flaresolverr_port_available": true' in output
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_ENABLED", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_PROVIDER", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_URL", None)


def test_upgrade_audit_script_can_wait_for_local_neo4j(monkeypatch, capsys) -> None:
    monkeypatch.setenv("NEO4J_URI", "neo4j://localhost:7687")
    monkeypatch.setattr(
        upgrade_audit,
        "wait_for_port",
        lambda host, port, timeout_seconds: (host, port, timeout_seconds) == ("127.0.0.1", 7687, 2),
    )
    monkeypatch.setattr(
        upgrade_audit,
        "audit_upgrade_capabilities",
        lambda strict_external=False: {
            "overall_status": "ready",
            "summary": {"ready": 15, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 1, "total_checks": 1},
            "checks": [],
            "failures": [],
        },
    )

    exit_code = upgrade_audit.main(["--wait-local-neo4j", "2"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Local Neo4j wait: ready within 2s" in output


def test_upgrade_audit_script_can_wait_for_browserless_before_applying_defaults(monkeypatch, capsys) -> None:
    for key in (
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    monkeypatch.setattr(
        upgrade_audit,
        "company_filing_playwright_browser_status",
        lambda: {"dependency_available": False, "browser_available": False},
    )
    monkeypatch.setattr(upgrade_audit, "is_port_open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        upgrade_audit,
        "wait_for_port",
        lambda host, port, timeout_seconds: (host, port, timeout_seconds) == ("127.0.0.1", 3000, 3),
    )
    captured = {}

    def fake_audit(strict_external=False):
        captured["browser_render_enabled"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_ENABLED")
        captured["browser_render_url"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_URL")
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--wait-local-browserless", "3", "--local-browser-render-defaults"])

    assert exit_code == 0
    assert captured["browser_render_enabled"] == "true"
    assert captured["browser_render_url"].startswith("http://127.0.0.1:3000/content")
    output = capsys.readouterr().out
    assert "Local Browserless wait: ready within 3s" in output
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_ENABLED", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_PROVIDER", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_URL", None)


def test_upgrade_audit_script_can_wait_for_flaresolverr_before_applying_defaults(monkeypatch, capsys) -> None:
    for key in (
        "COMPANY_FILING_PROXY_URLS",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    monkeypatch.setattr(
        upgrade_audit,
        "company_filing_playwright_browser_status",
        lambda: {"dependency_available": False, "browser_available": False},
    )
    monkeypatch.setattr(upgrade_audit, "is_port_open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        upgrade_audit,
        "wait_for_port",
        lambda host, port, timeout_seconds: (host, port, timeout_seconds) == ("127.0.0.1", 8191, 3),
    )
    captured = {}

    def fake_audit(strict_external=False):
        captured["browser_render_provider"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_PROVIDER")
        captured["browser_render_url"] = os.environ.get("COMPANY_FILING_BROWSER_RENDER_URL")
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(
        ["--wait-local-flaresolverr", "3", "--local-browser-render-defaults", "--prefer-unlocker"]
    )

    assert exit_code == 0
    assert captured == {
        "browser_render_provider": "flaresolverr",
        "browser_render_url": "http://127.0.0.1:8191/v1",
    }
    output = capsys.readouterr().out
    assert "Local FlareSolverr wait: ready within 3s" in output
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_ENABLED", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_PROVIDER", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_URL", None)


def test_upgrade_audit_script_can_report_local_docker_image_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        upgrade_audit,
        "audit_upgrade_capabilities",
        lambda strict_external=False: {
            "overall_status": "caution",
            "summary": {"ready": 14, "warnings": 2, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "caution", "ready": 0, "total_checks": 2},
            "checks": [],
            "failures": [],
        },
    )

    def fake_run(command, **kwargs):
        image = command[-1]
        return subprocess.CompletedProcess(
            command,
            0 if image == "neo4j:5-community" else 1,
            stdout="ok" if image == "neo4j:5-community" else "",
            stderr="" if image == "neo4j:5-community" else "missing image",
        )

    monkeypatch.setattr("app.services.local_dependency_diagnostics.subprocess.run", fake_run)

    exit_code = upgrade_audit.main(["--check-local-docker-images"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "neo4j=present" in output
    assert "redis=missing" in output
    assert "postgres=missing" in output
    assert "browserless=missing" in output
    assert "chroma=missing" in output
    assert "docker compose pull redis postgres browserless chroma" in output


def test_upgrade_audit_script_includes_flaresolverr_image_when_unlocker_is_preferred(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        upgrade_audit,
        "audit_upgrade_capabilities",
        lambda strict_external=False: {
            "overall_status": "caution",
            "summary": {"ready": 14, "warnings": 2, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "caution", "ready": 0, "total_checks": 2},
            "checks": [],
            "failures": [],
        },
    )

    def fake_run(command, **kwargs):
        image = command[-1]
        return subprocess.CompletedProcess(
            command,
            0 if image != "ghcr.io/flaresolverr/flaresolverr:latest" else 1,
            stdout="ok" if image != "ghcr.io/flaresolverr/flaresolverr:latest" else "",
            stderr="" if image != "ghcr.io/flaresolverr/flaresolverr:latest" else "missing image",
        )

    monkeypatch.setattr("app.services.local_dependency_diagnostics.subprocess.run", fake_run)

    exit_code = upgrade_audit.main(["--check-local-docker-images", "--prefer-unlocker"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "flaresolverr=missing" in output
    assert "docker compose pull flaresolverr" in output


def test_local_docker_image_status_is_machine_readable(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        image = command[-1]
        return subprocess.CompletedProcess(command, 0 if image == "present:latest" else 1)

    monkeypatch.setattr("app.services.local_dependency_diagnostics.subprocess.run", fake_run)

    status = upgrade_audit.local_docker_image_status(
        {"present_service": "present:latest", "missing_service": "missing:latest"}
    )

    assert status["docker_available"] is True
    assert status["all_present"] is False
    assert status["missing_services"] == ["missing_service"]
    assert status["images"][0] == {
        "service": "present_service",
        "image": "present:latest",
        "present": True,
        "error": None,
    }
