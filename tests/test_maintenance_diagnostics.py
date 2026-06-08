from __future__ import annotations

import subprocess

import pytest

from app.services import maintenance_diagnostics


def test_maintenance_diagnostic_action_catalog_exposes_allowlisted_read_only_actions() -> None:
    catalog = maintenance_diagnostics.maintenance_diagnostic_action_catalog()

    action_ids = {action["id"] for action in catalog["actions"]}
    assert catalog["collector_path"] == "app/services/maintenance_diagnostics.py"
    assert catalog["execution_policy"] == "allowlisted_read_only_subprocess"
    assert action_ids == {
        "celery_inspect_ping",
        "company_filing_render_smoke",
        "external_deployment_env_check",
        "external_deployment_env_gaps",
        "external_integrations_smoke",
        "graphrag_live_query_smoke",
        "graphrag_local_contract_smoke",
        "high_risk_unlocker_smoke",
        "local_neo4j_upgrade_audit",
        "local_unlocker_upgrade_audit",
        "neo4j_payload_dry_run",
        "upgrade_audit",
    }
    assert all(action["read_only"] is True for action in catalog["actions"])
    assert all("display_command" in action for action in catalog["actions"])
    assert all("argv" not in action for action in catalog["actions"])
    env_gap_action = {
        action["id"]: action for action in catalog["actions"]
    }["external_deployment_env_gaps"]
    assert "external_deployment_env_gaps.py --json" in env_gap_action["display_command"]
    assert "需人工補密鑰" in env_gap_action["description"]
    env_check_action = {
        action["id"]: action for action in catalog["actions"]
    }["external_deployment_env_check"]
    assert "--env-check --env-check-target all --env-file .env" in (
        env_check_action["display_command"]
    )
    assert "遮蔽密鑰" in env_check_action["description"]
    neo4j_action = {
        action["id"]: action for action in catalog["actions"]
    }["local_neo4j_upgrade_audit"]
    assert "--local-neo4j-defaults --wait-local-neo4j 20 --json" in (
        neo4j_action["display_command"]
    )
    unlocker_audit_action = {
        action["id"]: action for action in catalog["actions"]
    }["local_unlocker_upgrade_audit"]
    assert "--prefer-unlocker" in unlocker_audit_action["display_command"]
    assert "--wait-local-flaresolverr 20" in unlocker_audit_action["display_command"]
    assert "--local-browser-render-defaults --json" in (
        unlocker_audit_action["display_command"]
    )
    live_query_action = {
        action["id"]: action for action in catalog["actions"]
    }["graphrag_live_query_smoke"]
    assert "--import-first" not in live_query_action["display_command"]
    mops_action = {
        action["id"]: action for action in catalog["actions"]
    }["high_risk_unlocker_smoke"]
    assert "https://mops.twse.com.tw/" in mops_action["display_command"]


def test_run_maintenance_diagnostic_action_executes_only_allowlisted_action(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        captured["timeout"] = kwargs["timeout"]
        captured["check"] = kwargs["check"]
        captured["text"] = kwargs["text"]
        captured["capture_output"] = kwargs["capture_output"]
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "upgrade_audit",
        root=tmp_path,
    )

    assert result["status"] == "success"
    assert result["returncode"] == 0
    assert result["stdout_tail"] == "ok\n"
    assert result["stderr_tail"] == ""
    assert result["display_command"] == ".venv/bin/python scripts/upgrade_audit.py"
    assert captured["command"][1:] == ["scripts/upgrade_audit.py"]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] == 90
    assert captured["check"] is False
    assert captured["text"] is True
    assert captured["capture_output"] is True


def test_run_maintenance_diagnostic_action_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="Unknown maintenance diagnostic action"):
        maintenance_diagnostics.run_maintenance_diagnostic_action("rm -rf")


def test_run_maintenance_diagnostic_action_rejects_non_read_only_action(monkeypatch) -> None:
    monkeypatch.setattr(
        maintenance_diagnostics,
        "MAINTENANCE_DIAGNOSTIC_ACTIONS",
        {
            "unsafe_action": {
                "id": "unsafe_action",
                "read_only": False,
            }
        },
    )

    with pytest.raises(ValueError, match="not read-only"):
        maintenance_diagnostics.run_maintenance_diagnostic_action("unsafe_action")


def test_run_maintenance_diagnostic_action_reports_timeout(monkeypatch, tmp_path) -> None:
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            timeout=kwargs["timeout"],
            output="partial",
            stderr="late stderr",
        )

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "celery_inspect_ping",
        root=tmp_path,
    )

    assert result["status"] == "timeout"
    assert result["returncode"] is None
    assert result["stdout_tail"] == "partial"
    assert result["stderr_tail"] == "late stderr"
    assert result["message"] == "診斷逾時：20s"
