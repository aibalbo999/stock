from __future__ import annotations

import json
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
        "task_submission_smoke",
        "upgrade_audit",
    }
    assert all(action["read_only"] is True for action in catalog["actions"])
    assert all("display_command" in action for action in catalog["actions"])
    assert all("argv" not in action for action in catalog["actions"])
    upgrade_action = {
        action["id"]: action for action in catalog["actions"]
    }["upgrade_audit"]
    assert "upgrade_audit.py --auto-local-defaults --json" in (
        upgrade_action["display_command"]
    )
    env_gap_action = {
        action["id"]: action for action in catalog["actions"]
    }["external_deployment_env_gaps"]
    assert "external_deployment_env_gaps.py --json" in env_gap_action["display_command"]
    assert "需人工補密鑰" in env_gap_action["description"]
    env_check_action = {
        action["id"]: action for action in catalog["actions"]
    }["external_deployment_env_check"]
    assert "--env-check --env-check-target all --env-file .env --json" in (
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
    task_submission_action = {
        action["id"]: action for action in catalog["actions"]
    }["task_submission_smoke"]
    assert "task_submission_smoke.py --json" in (
        task_submission_action["display_command"]
    )
    assert "不送出 Celery 任務" in task_submission_action["description"]


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
    assert result["summary_rows"] == []
    assert result["display_command"] == (
        ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
    )
    assert captured["command"][1:] == [
        "scripts/upgrade_audit.py",
        "--auto-local-defaults",
        "--json",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] == 90
    assert captured["check"] is False
    assert captured["text"] is True
    assert captured["capture_output"] is True


def test_run_maintenance_diagnostic_action_executes_task_submission_readiness_smoke(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"passed"}', stderr="")

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "task_submission_smoke",
        root=tmp_path,
    )

    assert result["status"] == "success"
    assert result["display_command"] == (
        ".venv/bin/python scripts/task_submission_smoke.py --json"
    )
    assert captured["command"][1:] == ["scripts/task_submission_smoke.py", "--json"]
    assert captured["timeout"] == 30


def test_run_maintenance_diagnostic_action_summarizes_upgrade_audit_json(
    monkeypatch,
    tmp_path,
) -> None:
    payload = {
        "overall_status": "ready",
        "summary": {
            "deployment_status": "caution",
            "failures": 0,
            "implementation_status": "ready",
            "optional_warnings": 4,
            "ready": 28,
            "total_checks": 32,
            "total_warnings": 4,
        },
        "external_deployment_enablement": {
            "pending": 4,
            "ready": 3,
            "free_local_pending": 3,
            "local_action_available": 3,
            "quota_or_external_pending": 0,
            "paid_external_pending": 1,
            "primary_next_action": "先處理本機免費可補強項目。",
        },
        "external_deployment_pending_gap_action_counts": {
            "local_action": 3,
            "quota_or_external": 0,
            "paid_external": 1,
            "manual_configuration": 0,
        },
        "all_warnings": [
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "外部 Neo4j 匯入連線",
                "ready": False,
                "status": "degraded",
                "enablement_profile": {"group_label": "可本機免費啟用"},
                "remediation": "啟動本機 Neo4j 後重跑 smoke。",
            }
        ],
    }

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "upgrade_audit",
        root=tmp_path,
    )

    rows = result["summary_rows"]
    assert rows[0]["項目"] == "Upgrade audit"
    assert rows[0]["Ready"] == "28/32"
    assert "warnings=4" in rows[0]["數量"]
    assert rows[1]["項目"] == "外部部署啟用"
    assert "free_local=3" in rows[1]["Ready"]
    assert rows[2]["項目"] == "外部缺口處理類型"
    assert "local_action=3" in rows[2]["狀態"]
    assert "paid=1" in rows[2]["數量"]
    assert "先執行本機啟動/驗證指令" in rows[2]["下一步"]
    assert rows[3]["項目"] == "外部 Neo4j 匯入連線"
    assert rows[3]["Ready"] == "否"
    assert rows[3]["數量"] == "可本機免費啟用"


def test_run_maintenance_diagnostic_action_summarizes_external_smoke_gap_actions(
    monkeypatch,
    tmp_path,
) -> None:
    payload = {
        "status": "caution",
        "ready_count": 5,
        "check_count": 9,
        "actionable_check_count": 9,
        "strict_command": ".venv/bin/python scripts/external_integrations_smoke.py --strict --json",
        "enablement_summary": {
            "pending": 4,
            "ready": 1,
            "free_local_pending": 3,
            "local_action_available": 3,
            "quota_or_external_pending": 0,
            "paid_external_pending": 1,
            "primary_next_action": "先處理本機免費可補強項目。",
        },
        "pending_gap_action_counts": {
            "local_action": 3,
            "quota_or_external": 0,
            "paid_external": 1,
            "manual_configuration": 0,
        },
        "checks": [
            {
                "label": "Structured company filing API fallback",
                "status": "not_configured",
                "ready": False,
                "remediation": "設定 TEJ 或專業資料 API。",
                "enablement_profile": {"group_label": "需外部資料 API"},
            }
        ],
    }

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "external_integrations_smoke",
        root=tmp_path,
    )

    rows = result["summary_rows"]
    assert rows[0]["項目"] == "External integrations smoke"
    assert rows[0]["Ready"] == "5/9"
    assert rows[1]["項目"] == "外部部署啟用"
    assert rows[2]["項目"] == "外部缺口處理類型"
    assert "local_action=3" in rows[2]["狀態"]
    assert "paid=1" in rows[2]["數量"]
    assert rows[3]["項目"] == "Structured company filing API fallback"


def test_run_maintenance_diagnostic_action_summarizes_graphrag_json(
    monkeypatch,
    tmp_path,
) -> None:
    payload = {
        "status": "ready",
        "ready": True,
        "import_first": False,
        "local_contract": True,
        "payload": {
            "format": "neo4j_cypher_v1",
            "ready": True,
            "node_count": 4,
            "structural_edge_count": 3,
            "peer_edge_count": 0,
            "statement_count": 5,
        },
        "query_result": {
            "local_dry_run": {
                "ready": True,
                "row_count": 2,
                "status": "executed_dry_run",
            },
            "plan": {
                "cypher": "MATCH path = shortestPath((source)-[*..3]-(target)) RETURN path",
                "intent": "shortest_path_between_companies",
            },
        },
    }

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "graphrag_local_contract_smoke",
        root=tmp_path,
    )

    rows = result["summary_rows"]
    assert rows[0]["項目"] == "GraphRAG smoke"
    assert rows[0]["Ready"] == "是"
    assert "local_contract=True" in rows[0]["數量"]
    assert rows[1]["項目"] == "Neo4j payload"
    assert "nodes=4" in rows[1]["數量"]
    assert rows[2]["項目"] == "Cypher query"
    assert "rows=2" in rows[2]["數量"]


def test_run_maintenance_diagnostic_action_summarizes_external_env_check_json(
    monkeypatch,
    tmp_path,
) -> None:
    payload = {
        "status": "action_required",
        "target": "all",
        "targets": ["host", "compose"],
        "env_file": ".env",
        "gap_count": 2,
        "checks": {
            "host": {
                "status": "review_required",
                "target": "host",
                "env_file_exists": True,
                "checked_count": 2,
                "set_count": 1,
                "missing_count": 0,
                "different_count": 1,
                "rows": [
                    {
                        "status": "different",
                        "env_key": "COMPANY_FILING_STRUCTURED_API_PROVIDER",
                        "action": "確認部署目標是否正確。",
                    }
                ],
            },
            "compose": {
                "status": "action_required",
                "target": "compose",
                "env_file_exists": True,
                "checked_count": 2,
                "set_count": 0,
                "missing_count": 2,
                "different_count": 0,
                "rows": [
                    {
                        "status": "missing",
                        "env_key": "COMPOSE_NEO4J_URI",
                        "action": "加入 COMPOSE_NEO4J_URI=neo4j://neo4j:7687。",
                    }
                ],
            },
        },
    }

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "external_deployment_env_check",
        root=tmp_path,
    )

    rows = result["summary_rows"]
    assert rows[0]["項目"] == "External env check"
    assert rows[0]["狀態"] == "action_required"
    assert "target=all" in rows[0]["Ready"]
    assert rows[1]["項目"] == "host env"
    assert rows[1]["Ready"] == "1/2"
    assert "different=1" in rows[1]["數量"]
    assert rows[2]["項目"] == "compose env"
    assert "missing=2" in rows[2]["數量"]
    assert "COMPOSE_NEO4J_URI" in rows[2]["下一步"]
    assert "real-secret" not in str(rows)


def test_run_maintenance_diagnostic_action_summarizes_task_submission_smoke_json(
    monkeypatch,
    tmp_path,
) -> None:
    payload = {
        "status": "caution",
        "submit": True,
        "wait": True,
        "next_actions": ["重啟 FastAPI 與 Celery worker 後重跑 smoke。"],
        "checks": [
            {"status": "passed", "label": "Services status"},
            {"status": "warning", "label": "Worker offline"},
        ],
        "task_queue": {
            "ready": False,
            "processing_ready": True,
            "worker_online": False,
            "legacy_status_shape": True,
            "status_shape_warning": "目前 API runtime 回傳 legacy celery status。",
        },
        "runtime_identity": {
            "status": "failed",
            "expected_commit_short": "new-commit",
            "actual_commit_short": "old-commit",
            "reason": "api_runtime_commit_mismatch",
        },
        "submission": {
            "ok": True,
            "status_code": 202,
            "url": "http://127.0.0.1:8000/tasks/data-operation",
            "json": {"task_id": "abc-123"},
        },
        "task_poll": {
            "status": "finished",
            "ready": True,
            "successful": True,
            "task_status": "SUCCESS",
        },
    }

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(maintenance_diagnostics.subprocess, "run", fake_run)

    result = maintenance_diagnostics.run_maintenance_diagnostic_action(
        "task_submission_smoke",
        root=tmp_path,
    )

    rows = result["summary_rows"]
    assert rows[0]["項目"] == "Task submission smoke"
    assert rows[0]["狀態"] == "caution"
    assert "submit=True" in rows[0]["Ready"]
    assert "warnings=1" in rows[0]["數量"]
    assert "重啟 FastAPI" in rows[0]["下一步"]
    assert rows[1]["項目"] == "API runtime identity"
    assert rows[1]["狀態"] == "failed"
    assert rows[1]["Ready"] == "new-commit"
    assert rows[1]["數量"] == "old-commit"
    assert rows[1]["下一步"] == "api_runtime_commit_mismatch"
    assert rows[2]["項目"] == "Task queue"
    assert rows[2]["狀態"] == "not_ready"
    assert "worker=False" in rows[2]["Ready"]
    assert "legacy_status_shape=True" in rows[2]["數量"]
    assert rows[3]["項目"] == "Data operation submission"
    assert rows[3]["狀態"] == "ok"
    assert rows[3]["Ready"] == "202"
    assert rows[3]["數量"] == "abc-123"
    assert rows[4]["項目"] == "Task polling"
    assert rows[4]["狀態"] == "finished"
    assert "successful=True" in rows[4]["Ready"]
    assert rows[4]["數量"] == "SUCCESS"


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
    assert result["summary_rows"] == []
    assert result["message"] == "診斷逾時：20s"
