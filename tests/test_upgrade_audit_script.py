from __future__ import annotations

import os
import subprocess

from scripts import upgrade_audit


def test_upgrade_audit_script_prints_text_and_returns_success_for_warnings(
    monkeypatch, capsys
) -> None:
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
                "deployment_blocking_status": "ready",
                "deployment_optional_only": True,
            },
            "implementation": {"status": "ready", "ready": 1, "total_checks": 1},
            "deployment": {
                "status": "caution",
                "blocking_status": "ready",
                "optional_only": True,
                "ready": 0,
                "total_checks": 1,
            },
            "local_dependencies": {
                "status": "partial",
                "open_services": ["redis"],
                "missing_core_services": ["neo4j"],
                "last_start": {
                    "available": True,
                    "path": "data/local_dependency_start_status.json",
                    "updated_at": "2026-06-09T01:02:03Z",
                    "status": "已啟動",
                },
            },
            "external_deployment_enablement": {
                "total": 1,
                "ready": 0,
                "pending": 1,
                "blocking_pending": 0,
                "nonblocking_optional_pending": 1,
                "free_local_pending": 1,
                "local_action_available": 1,
                "quota_or_external_pending": 0,
                "paid_external_pending": 0,
                "primary_next_action": "先處理本機免費可補強項目，再評估 API 額度或付費資料商。",
            },
            "external_deployment_pending_gap_action_counts": {
                "local_action": 1,
                "quota_or_external": 0,
                "paid_external": 0,
                "manual_configuration": 0,
            },
            "external_deployment_local_projection": {
                "current_pending": 1,
                "remaining_pending": 0,
                "remaining_blocking_pending": 0,
                "remaining_optional_pending": 0,
                "remaining_paid_external_pending": 0,
                "available_local_default_gap_count": 1,
                "next_action": "套用已偵測本機 defaults 可消除 1 項外部選配缺口。",
            },
            "external_deployment_pending_gaps": [
                {
                    "capability": "neo4j_import",
                    "action_type": "local_action",
                    "decision": "需要該能力時配置",
                    "local_action_state": "可啟動",
                    "local_action_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
                }
            ],
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
                    "enablement_profile": {
                        "group_label": "可本機免費啟用",
                        "cost_label": "本機 Neo4j 免費；託管 Neo4j 依方案",
                    },
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
    assert "External integrations: caution (0/1 ready; blocking=ready)" in output
    assert (
        "Deployment note: no blocking deployment gaps; remaining warnings are optional external integrations."
        in output
    )
    assert "Checks: 1 ready, 0 warnings, 1 optional deployment warnings, 0 failures" in output
    assert (
        "External enablement: pending=1; blocking_pending=0; optional_pending=1; "
        "free_local=1; local_action=1; "
        "quota_or_external=0; paid_external=0"
    ) in output
    assert "External next action: 先處理本機免費可補強項目" in output
    assert (
        "External gap actions: local_action=1; quota_or_external=0; "
        "paid_external=0; manual_configuration=0"
    ) in output
    assert (
        "Effective external gaps: pending=1 -> 0 after available local defaults; "
        "blocking=0; optional=0; paid_external=0; local_defaults=1"
    ) in output
    assert "Effective next action: 套用已偵測本機 defaults 可消除 1 項外部選配缺口。" in output
    assert "Local dependency runtime: partial; open=redis; missing_core=neo4j" in output
    assert (
        "Local dependency last start: 已啟動 at 2026-06-09T01:02:03Z; "
        "path=data/local_dependency_start_status.json"
    ) in output
    assert "[WARN optional] ai_rag.neo4j_import" in output
    assert "enablement: 可本機免費啟用; cost: 本機 Neo4j 免費" in output
    assert "action: local_action (需要該能力時配置; 可啟動)" in output
    assert "command: .venv/bin/python scripts/start_system.py --start-dependencies" in output


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


def test_upgrade_audit_script_can_apply_local_chroma_defaults(monkeypatch, capsys) -> None:
    for key in ("USE_CHROMA", "CHROMA_API_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    captured = {}

    def fake_audit(strict_external=False):
        captured["use_chroma"] = os.environ.get("USE_CHROMA")
        captured["chroma_api_url"] = os.environ.get("CHROMA_API_URL")
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--local-chroma-defaults", "--json"])

    assert exit_code == 0
    assert captured == {
        "use_chroma": "true",
        "chroma_api_url": "http://127.0.0.1:8001",
    }
    output = capsys.readouterr().out
    assert '"local_chroma_defaults"' in output
    assert "CHROMA_API_URL" in output
    os.environ.pop("USE_CHROMA", None)
    os.environ.pop("CHROMA_API_URL", None)


def test_upgrade_audit_script_auto_applies_reachable_local_defaults(
    monkeypatch,
    capsys,
) -> None:
    for key in (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "USE_CHROMA",
        "CHROMA_API_URL",
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
        lambda host, port: (host, port)
        in {
            ("127.0.0.1", 7687),
            ("127.0.0.1", 8191),
        },
    )
    monkeypatch.setattr(upgrade_audit, "http_ok", lambda url: url.endswith("/api/v2/heartbeat"))
    captured = {}

    def fake_audit(strict_external=False):
        captured["neo4j_uri"] = os.environ.get("NEO4J_URI")
        captured["use_chroma"] = os.environ.get("USE_CHROMA")
        captured["browser_render_provider"] = os.environ.get(
            "COMPANY_FILING_BROWSER_RENDER_PROVIDER"
        )
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

    exit_code = upgrade_audit.main(["--auto-local-defaults", "--json"])

    assert exit_code == 0
    assert captured == {
        "neo4j_uri": "neo4j://localhost:7687",
        "use_chroma": "true",
        "browser_render_provider": "flaresolverr",
        "browser_render_url": "http://127.0.0.1:8191/v1",
    }
    output = capsys.readouterr().out
    assert '"local_dependency_auto_defaults"' in output
    assert '"applied_groups": [' in output
    assert '"flaresolverr"' in output
    assert "NEO4J_PASSWORD" in output
    assert "stock_ai_neo4j_password" not in output
    for key in (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "USE_CHROMA",
        "CHROMA_API_URL",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    ):
        os.environ.pop(key, None)


def test_upgrade_audit_script_auto_defaults_skip_unreachable_services(
    monkeypatch,
    capsys,
) -> None:
    for key in (
        "NEO4J_URI",
        "USE_CHROMA",
        "CHROMA_API_URL",
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    monkeypatch.setattr(upgrade_audit, "is_port_open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(upgrade_audit, "http_ok", lambda _url: False)
    monkeypatch.setattr(
        upgrade_audit,
        "company_filing_playwright_browser_status",
        lambda: {"dependency_available": False, "browser_available": False},
    )
    captured = {}

    def fake_audit(strict_external=False):
        captured["neo4j_uri"] = os.environ.get("NEO4J_URI")
        captured["use_chroma"] = os.environ.get("USE_CHROMA")
        captured["browser_render_enabled"] = os.environ.get(
            "COMPANY_FILING_BROWSER_RENDER_ENABLED"
        )
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--auto-local-defaults", "--json"])

    assert exit_code == 0
    assert captured == {
        "neo4j_uri": None,
        "use_chroma": None,
        "browser_render_enabled": None,
    }
    output = capsys.readouterr().out
    assert '"local_dependency_auto_defaults"' in output
    assert '"applied_env_keys": []' in output


def test_upgrade_audit_script_waits_for_local_chroma(monkeypatch, capsys) -> None:
    monkeypatch.setenv("USE_CHROMA", "true")
    monkeypatch.setenv("CHROMA_API_URL", "http://127.0.0.1:8001")
    monkeypatch.setattr(upgrade_audit, "clear_settings_cache", lambda: None)
    monkeypatch.setattr(upgrade_audit, "wait_for_http_ok", lambda url, timeout_seconds: True)

    def fake_audit(strict_external=False):
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--wait-local-chroma", "7"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Local Chroma wait: ready within 7s" in output
    os.environ.pop("USE_CHROMA", None)
    os.environ.pop("CHROMA_API_URL", None)


def test_upgrade_audit_script_checks_core_images_plus_unlocker(monkeypatch, capsys) -> None:
    captured = {}

    def fake_local_docker_image_status(images=None):
        captured["services"] = sorted((images or {}).keys())
        return {
            "images": [
                {"service": service, "present": True}
                for service in captured["services"]
            ],
            "remediation": None,
        }

    def fake_audit(strict_external=False):
        return {
            "overall_status": "ready",
            "summary": {"ready": 16, "warnings": 0, "failures": 0},
            "implementation": {"status": "ready", "ready": 14, "total_checks": 14},
            "deployment": {"status": "ready", "ready": 2, "total_checks": 2},
            "checks": [],
            "failures": [],
        }

    monkeypatch.setattr(upgrade_audit, "local_docker_image_status", fake_local_docker_image_status)
    monkeypatch.setattr(upgrade_audit, "audit_upgrade_capabilities", fake_audit)

    exit_code = upgrade_audit.main(["--check-local-docker-images", "--prefer-unlocker"])

    assert exit_code == 0
    assert captured["services"] == [
        "browserless",
        "chroma",
        "flaresolverr",
        "neo4j",
        "postgres",
        "redis",
    ]
    output = capsys.readouterr().out
    assert "Local docker images: browserless=present" in output
    assert "chroma=present" in output
    assert "flaresolverr=present" in output


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
        captured["browser_render_provider"] = os.environ.get(
            "COMPANY_FILING_BROWSER_RENDER_PROVIDER"
        )
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
        ["--local-browser-render-defaults", "--prefer-unlocker", "--json"]
    )

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


def test_upgrade_audit_script_can_wait_for_browserless_before_applying_defaults(
    monkeypatch, capsys
) -> None:
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

    exit_code = upgrade_audit.main(
        ["--wait-local-browserless", "3", "--local-browser-render-defaults"]
    )

    assert exit_code == 0
    assert captured["browser_render_enabled"] == "true"
    assert captured["browser_render_url"].startswith("http://127.0.0.1:3000/content")
    output = capsys.readouterr().out
    assert "Local Browserless wait: ready within 3s" in output
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_ENABLED", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_PROVIDER", None)
    os.environ.pop("COMPANY_FILING_BROWSER_RENDER_URL", None)


def test_upgrade_audit_script_can_wait_for_flaresolverr_before_applying_defaults(
    monkeypatch, capsys
) -> None:
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
        captured["browser_render_provider"] = os.environ.get(
            "COMPANY_FILING_BROWSER_RENDER_PROVIDER"
        )
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


def test_upgrade_audit_script_includes_flaresolverr_image_when_unlocker_is_preferred(
    monkeypatch, capsys
) -> None:
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
