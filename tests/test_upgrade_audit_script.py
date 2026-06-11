from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
            "optimization_progress": {
                "status": "ready_with_optional_gaps",
                "total_checks": 33,
                "ready_checks": 29,
                "completion_ratio": 0.8788,
                "blocking_gap_count": 0,
                "optional_gap_count": 4,
                "local_resolvable_gap_count": 3,
                "effective_blocking_gap_count_after_available_local_defaults": 0,
                "effective_optional_gap_count_after_available_local_defaults": 1,
                "primary_next_action": {
                    "label": "本機 defaults 可驗證",
                    "next_action": (
                        "先執行本機 defaults audit；可用本機 defaults 驗證 3 項缺口，"
                        "之後剩餘 1 項外部/付費選配。"
                    ),
                    "verify_command": (
                        ".venv/bin/python scripts/upgrade_audit.py "
                        "--local-neo4j-defaults --prefer-unlocker --json"
                    ),
                },
            },
            "optimization_progress_scope": {
                "scope": "optimization_objective",
                "optimization_check_count": 33,
                "audit_check_count": 34,
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
    assert "升級檢查: ready" in output
    assert "核心實作: ready (1/1 就緒)" in output
    assert "外部部署選配: caution (0/1 就緒；阻塞=ready)" in output
    assert (
        "部署提醒: 沒有阻塞型部署缺口；剩餘提醒都是外部整合選配。"
        in output
    )
    assert "檢查結果: 1 就緒，0 警示，1 個外部部署選配提醒，0 失敗" in output
    assert (
        "外部選配啟用摘要: 待處理=1；阻塞=0；選配=1；"
        "本機免費=1；可本機處理=1；"
        "需額度/外部=0；付費外部=0"
    ) in output
    assert "外部選配建議: 先處理本機免費可補強項目" in output
    assert (
        "外部缺口分類: 本機動作=1；額度/外部=0；"
        "付費外部=0；手動設定=0"
    ) in output
    assert (
        "套用本機預設後的外部缺口: 待處理=1 -> 0；"
        "阻塞=0；選配=0；付費外部=0；本機預設=1"
    ) in output
    assert "有效建議: 套用已偵測本機 defaults 可消除 1 項外部選配缺口。" in output
    assert (
        "優化目標進度: ready_with_optional_gaps "
        "(29/33 就緒；阻塞=0；選配=4；本機可解=3；"
        "有效選配=1)"
    ) in output
    assert (
        "優化範圍: 33 個目標檢查；34 個升級檢查；"
        "部署預檢不列入目標=architecture.python_runtime"
    ) in output
    assert "優化建議: 本機 defaults 可驗證" in output
    assert "優化指令: .venv/bin/python scripts/upgrade_audit.py --local-neo4j-defaults --prefer-unlocker --json" in output
    assert "本機依賴狀態: partial；已開啟=redis；缺少核心=neo4j" in output
    assert (
        "本機依賴上次啟動: 已啟動；時間=2026-06-09T01:02:03Z；"
        "路徑=data/local_dependency_start_status.json"
    ) in output
    assert "[WARN 選配] ai_rag.neo4j_import" in output
    assert "啟用分類: 可本機免費啟用；成本: 本機 Neo4j 免費" in output
    assert "缺口處理: local_action (需要該能力時配置；可啟動)" in output
    assert "指令: .venv/bin/python scripts/start_system.py --start-dependencies" in output


def test_upgrade_audit_script_surfaces_paid_external_free_validation(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        upgrade_audit,
        "audit_upgrade_capabilities",
        lambda strict_external=False: {
            "overall_status": "ready",
            "summary": {
                "ready": 32,
                "warnings": 0,
                "optional_warnings": 1,
                "total_warnings": 1,
                "failures": 0,
                "deployment_blocking_status": "ready",
                "deployment_optional_only": True,
            },
            "implementation": {"status": "ready", "ready": 32, "total_checks": 32},
            "deployment": {
                "status": "caution",
                "blocking_status": "ready",
                "optional_only": True,
                "ready": 0,
                "total_checks": 1,
            },
            "optimization_progress": {
                "status": "ready_with_optional_gaps",
                "total_checks": 32,
                "ready_checks": 31,
                "blocking_gap_count": 0,
                "optional_gap_count": 1,
                "local_resolvable_gap_count": 0,
                "effective_optional_gap_count_after_available_local_defaults": 1,
                "primary_next_action": {
                    "label": "核心已完成",
                    "action_type": "optional_review",
                    "next_action": "目前沒有 blocking 程式缺口；剩餘 1 項依需求再啟用。",
                },
                "prioritized_next_actions": [
                    {
                        "capability": "company_filing_structured_api_fallback",
                        "label": "公司文件結構化 API 備援",
                        "action_type": "paid_external",
                        "cost_profile": "paid_external",
                        "next_action": "需要穩定法說會簡報時再串 TEJ 或專業資料 API。",
                        "free_validation_label": "樣本資料 + 本機測試 API + 提供者設定可驗證",
                        "free_validation_commands": [
                            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py --json --strict",
                            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py --provider-profile tej --json --strict",
                        ],
                    },
                ],
            },
            "checks": [],
            "failures": [],
            "warnings": [],
            "optional_warnings": [],
        },
    )

    assert upgrade_audit.main([]) == 0
    output = capsys.readouterr().out

    assert "優化建議: 核心已完成" in output
    assert (
        "優化免費驗證: 樣本資料 + 本機測試 API + 提供者設定可驗證；2 組檢查可先跑"
        in output
    )
    assert (
        "優化免費驗證指令: .venv/bin/python scripts/structured_company_filing_fixture_smoke.py --json --strict"
        in output
    )


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


def test_upgrade_audit_script_bootstraps_repo_root_for_task_exports() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/upgrade_audit.py", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.stdout, result.stderr
    audit = json.loads(result.stdout)
    background_task_queue = next(
        check for check in audit["checks"] if check["capability"] == "background_task_queue"
    )
    evidence = background_task_queue["evidence"]
    assert evidence["celery_app_available"] is True
    assert evidence["submission_contract_ready"] is True
    assert evidence["missing_task_exports"] == []


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
    assert os.environ.get("NEO4J_URI") is None
    assert os.environ.get("NEO4J_USER") is None
    assert os.environ.get("NEO4J_PASSWORD") is None
    assert os.environ.get("NEO4J_DATABASE") is None


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
    assert "本機 Chroma 等待: 就緒，7 秒內" in output
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
    assert "本機 Docker image: browserless=present" in output
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
    assert "本機 Neo4j 等待: 就緒，2 秒內" in output


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
    assert "本機 Browserless 等待: 就緒，3 秒內" in output
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
    assert "本機 FlareSolverr 等待: 就緒，3 秒內" in output
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
