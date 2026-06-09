from __future__ import annotations

from pathlib import Path

import pytest

from app.services import maintenance_operations


def test_maintenance_operation_catalog_exposes_allowlisted_local_dependency_operations() -> None:
    catalog = maintenance_operations.maintenance_operation_catalog()

    operation_ids = {operation["id"] for operation in catalog["operations"]}
    assert catalog["collector_path"] == "app/services/maintenance_operations.py"
    assert catalog["execution_policy"] == "allowlisted_local_dependency_operations"
    assert operation_ids == {
        "start_local_dependencies",
        "start_local_dependencies_with_unlocker",
    }
    assert all(operation["requires_confirmation"] is True for operation in catalog["operations"])
    assert all(operation["mutates_local_state"] is True for operation in catalog["operations"])
    assert all("display_command" in operation for operation in catalog["operations"])
    assert all(operation["post_run_checks"] for operation in catalog["operations"])
    assert all("argv" not in operation for operation in catalog["operations"])
    checks_by_id = {operation["id"]: operation["post_run_checks"] for operation in catalog["operations"]}
    assert any(
        "neo4j_graphrag_smoke.py" in check["command"]
        for check in checks_by_id["start_local_dependencies"]
    )
    assert any(
        check["diagnostic_action_id"] == "graphrag_local_contract_smoke"
        for check in checks_by_id["start_local_dependencies"]
    )
    assert any(
        check["diagnostic_action_id"] == "local_chroma_upgrade_audit"
        and "--local-chroma-defaults --wait-local-chroma 20" in check["command"]
        for check in checks_by_id["start_local_dependencies"]
    )
    assert all(
        check["diagnostic_action_id"] != "graphrag_live_query_smoke"
        for check in checks_by_id["start_local_dependencies"]
        if "--import-first" in check["command"]
    )
    assert any(
        "https://mops.twse.com.tw/" in check["command"]
        for check in checks_by_id["start_local_dependencies_with_unlocker"]
    )
    assert any(
        check["diagnostic_action_id"] == "local_unlocker_upgrade_audit"
        for check in checks_by_id["start_local_dependencies_with_unlocker"]
    )


def test_run_maintenance_operation_requires_confirmation() -> None:
    with pytest.raises(PermissionError, match="requires confirmation"):
        maintenance_operations.run_maintenance_operation("start_local_dependencies")


def test_run_maintenance_operation_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="Unknown maintenance operation"):
        maintenance_operations.run_maintenance_operation("rm-rf", confirmed=True)


def test_run_maintenance_operation_starts_core_dependencies(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_apply_defaults(**kwargs):
        captured["defaults"] = kwargs
        return {"NEO4J_URI": "neo4j://localhost:7687"}

    def fake_start(root: Path, **kwargs):
        captured["root"] = root
        captured["start"] = kwargs
        return {
            "status": "已啟動",
            "message": "Redis、Postgres 已送出啟動指令。",
            "services": ["redis", "postgres"],
        }

    def fake_wait(dependency_status, local_dependency_env, *, timeout_seconds):
        captured["wait_status_input"] = dependency_status
        captured["wait_env"] = local_dependency_env
        captured["wait_seconds"] = timeout_seconds
        return {"redis": True, "postgres": False}

    def fake_write(root, dependency_status, dependency_wait_status, local_dependency_env, **kwargs):
        captured["write"] = {
            "root": root,
            "status": dependency_status,
            "wait": dependency_wait_status,
            "env": local_dependency_env,
            "kwargs": kwargs,
        }
        return {"path": "data/local_dependency_start_status.json"}

    monkeypatch.setattr(
        maintenance_operations.startup,
        "apply_local_dependency_env_defaults",
        fake_apply_defaults,
    )
    monkeypatch.setattr(maintenance_operations.startup, "start_dependency_services", fake_start)
    monkeypatch.setattr(
        maintenance_operations.startup, "wait_for_local_dependency_ports", fake_wait
    )
    monkeypatch.setattr(
        maintenance_operations.startup,
        "fallback_local_browser_render_to_playwright",
        lambda *_args: {"status": "switched_to_playwright", "reason": "browserless_not_ready"},
    )
    monkeypatch.setattr(
        maintenance_operations.startup, "write_local_dependency_start_status", fake_write
    )

    result = maintenance_operations.run_maintenance_operation(
        "start_local_dependencies",
        confirmed=True,
        root=tmp_path,
    )

    assert result["status"] == "partial"
    assert result["message"] == "Redis、Postgres 已送出啟動指令。"
    assert result["wait"]["redis"] is True
    assert result["wait"]["postgres"] is False
    assert result["wait"]["browser_render_fallback"]["status"] == "switched_to_playwright"
    assert "- Postgres 5432：尚未就緒" in result["wait_lines"]
    assert result["start_record"]["path"] == "data/local_dependency_start_status.json"
    assert result["applied_env_keys"] == ["NEO4J_URI"]
    assert any(
        "upgrade_audit.py --local-neo4j-defaults" in check["command"]
        for check in result["post_run_checks"]
    )
    assert any(
        check["diagnostic_action_id"] == "local_neo4j_upgrade_audit"
        for check in result["post_run_checks"]
    )
    assert any(
        "neo4j_graphrag_smoke.py" in check["command"]
        for check in result["post_run_checks"]
    )
    assert any(
        "--local-chroma-defaults --wait-local-chroma 20" in check["command"]
        for check in result["post_run_checks"]
    )
    assert captured["root"] == tmp_path
    assert captured["defaults"] == {
        "enable_browser_render": True,
        "enable_chroma": True,
        "prefer_browserless": True,
        "prefer_unlocker": False,
    }
    assert captured["start"] == {
        "allow_pull_missing_images": False,
        "include_unlocker": False,
    }
    assert captured["wait_seconds"] == 10
    assert captured["write"]["kwargs"] == {
        "include_unlocker": False,
        "wait_seconds": 10,
    }


def test_run_maintenance_operation_can_prefer_unlocker(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_apply_defaults(**kwargs):
        captured["defaults"] = kwargs
        return {}

    def fake_start(root: Path, **kwargs):
        captured["root"] = root
        captured["start"] = kwargs
        return {"status": "已啟動", "message": "ok", "services": ["flaresolverr"]}

    def fake_write(*_args, **kwargs):
        captured["write"] = kwargs
        return {"path": "status.json"}

    monkeypatch.setattr(
        maintenance_operations.startup,
        "apply_local_dependency_env_defaults",
        fake_apply_defaults,
    )
    monkeypatch.setattr(maintenance_operations.startup, "start_dependency_services", fake_start)
    monkeypatch.setattr(
        maintenance_operations.startup,
        "wait_for_local_dependency_ports",
        lambda *_args, **_kwargs: {"flaresolverr": True},
    )
    monkeypatch.setattr(
        maintenance_operations.startup,
        "fallback_local_browser_render_to_playwright",
        lambda *_args: {},
    )
    monkeypatch.setattr(
        maintenance_operations.startup,
        "write_local_dependency_start_status",
        fake_write,
    )

    result = maintenance_operations.run_maintenance_operation(
        "start_local_dependencies_with_unlocker",
        confirmed=True,
        root=tmp_path,
    )

    assert result["status"] == "success"
    assert any(
        "mops.twse.com.tw" in check["command"]
        for check in result["post_run_checks"]
    )
    assert captured["defaults"]["prefer_browserless"] is False
    assert captured["defaults"]["prefer_unlocker"] is True
    assert captured["start"]["include_unlocker"] is True
    assert captured["write"]["include_unlocker"] is True


def test_run_maintenance_operation_reports_missing_images(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        maintenance_operations.startup,
        "apply_local_dependency_env_defaults",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        maintenance_operations.startup,
        "start_dependency_services",
        lambda *_args, **_kwargs: {
            "status": "需下載",
            "message": "缺少 Docker image：chroma。",
        },
    )
    monkeypatch.setattr(
        maintenance_operations.startup,
        "wait_for_local_dependency_ports",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        maintenance_operations.startup,
        "fallback_local_browser_render_to_playwright",
        lambda *_args: {},
    )
    monkeypatch.setattr(
        maintenance_operations.startup,
        "write_local_dependency_start_status",
        lambda *_args, **_kwargs: {"path": "status.json"},
    )

    result = maintenance_operations.run_maintenance_operation(
        "start_local_dependencies",
        confirmed=True,
        root=tmp_path,
    )

    assert result["status"] == "needs_download"
    assert result["message"] == "缺少 Docker image：chroma。"
