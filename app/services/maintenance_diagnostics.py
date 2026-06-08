from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_OUTPUT_CHARS = 4000
MAINTENANCE_DIAGNOSTIC_ACTIONS = {
    "upgrade_audit": {
        "id": "upgrade_audit",
        "label": "Upgrade audit",
        "description": "檢查核心升級能力與外部部署選配狀態。",
        "display_command": ".venv/bin/python scripts/upgrade_audit.py",
        "argv": [sys.executable, "scripts/upgrade_audit.py"],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "external_integrations_smoke": {
        "id": "external_integrations_smoke",
        "label": "External integrations smoke",
        "description": "執行外部整合 smoke contract，不會啟動選配服務。",
        "display_command": ".venv/bin/python scripts/external_integrations_smoke.py --json",
        "argv": [sys.executable, "scripts/external_integrations_smoke.py", "--json"],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "external_deployment_env_gaps": {
        "id": "external_deployment_env_gaps",
        "label": "External deployment env gaps",
        "description": "彙整外部部署選配缺少的 env key，區分本機可套用與需人工補密鑰。",
        "display_command": ".venv/bin/python scripts/external_deployment_env_gaps.py --json",
        "argv": [sys.executable, "scripts/external_deployment_env_gaps.py", "--json"],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "external_deployment_env_check": {
        "id": "external_deployment_env_check",
        "label": "External deployment env check",
        "description": "比對目前 .env 的 host/compose 外部部署設定狀態，輸出會遮蔽密鑰。",
        "display_command": (
            ".venv/bin/python scripts/external_deployment_env_gaps.py "
            "--env-check --env-check-target all --env-file .env"
        ),
        "argv": [
            sys.executable,
            "scripts/external_deployment_env_gaps.py",
            "--env-check",
            "--env-check-target",
            "all",
            "--env-file",
            ".env",
        ],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "celery_inspect_ping": {
        "id": "celery_inspect_ping",
        "label": "Celery inspect ping",
        "description": "檢查 Celery worker 是否回應目前設定的 Redis broker。",
        "display_command": (
            ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping"
        ),
        "argv": [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.tasks.celery_app.celery_app",
            "inspect",
            "ping",
        ],
        "timeout_seconds": 20,
        "read_only": True,
    },
    "local_neo4j_upgrade_audit": {
        "id": "local_neo4j_upgrade_audit",
        "label": "Local Neo4j upgrade audit",
        "description": "套用本機 Neo4j 預設值後檢查 GraphRAG live integration 狀態。",
        "display_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-neo4j-defaults --wait-local-neo4j 20 --json"
        ),
        "argv": [
            sys.executable,
            "scripts/upgrade_audit.py",
            "--local-neo4j-defaults",
            "--wait-local-neo4j",
            "20",
            "--json",
        ],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "local_unlocker_upgrade_audit": {
        "id": "local_unlocker_upgrade_audit",
        "label": "Local Neo4j + unlocker upgrade audit",
        "description": "套用本機 Neo4j 與 FlareSolverr 預設值後檢查外部選配狀態。",
        "display_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-neo4j-defaults --prefer-unlocker "
            "--wait-local-neo4j 20 --wait-local-flaresolverr 20 "
            "--local-browser-render-defaults --json"
        ),
        "argv": [
            sys.executable,
            "scripts/upgrade_audit.py",
            "--local-neo4j-defaults",
            "--prefer-unlocker",
            "--wait-local-neo4j",
            "20",
            "--wait-local-flaresolverr",
            "20",
            "--local-browser-render-defaults",
            "--json",
        ],
        "timeout_seconds": 120,
        "read_only": True,
    },
    "neo4j_payload_dry_run": {
        "id": "neo4j_payload_dry_run",
        "label": "Neo4j payload dry-run",
        "description": "確認 Neo4j 匯入 payload contract 可生成，不連線寫入 Neo4j。",
        "display_command": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
        "argv": [
            sys.executable,
            "-m",
            "scripts.import_supply_chain_graph_neo4j",
            "--dry-run",
        ],
        "timeout_seconds": 60,
        "read_only": True,
    },
    "graphrag_local_contract_smoke": {
        "id": "graphrag_local_contract_smoke",
        "label": "GraphRAG local contract smoke",
        "description": "確認 guarded Cypher planner 與本機 dry-run contract。",
        "display_command": (
            ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
            "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 "
            "--local-contract --json"
        ),
        "argv": [
            sys.executable,
            "scripts/neo4j_graphrag_smoke.py",
            "--tickers",
            "2330",
            "--target-ticker",
            "2382",
            "--question",
            "上下游衝擊",
            "--local-contract",
            "--json",
        ],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "graphrag_live_query_smoke": {
        "id": "graphrag_live_query_smoke",
        "label": "GraphRAG live query smoke",
        "description": "以目前 Neo4j 設定驗證 guarded live Cypher query，不執行 import-first 寫入。",
        "display_command": (
            ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
            "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
        ),
        "argv": [
            sys.executable,
            "scripts/neo4j_graphrag_smoke.py",
            "--tickers",
            "2330",
            "--target-ticker",
            "2382",
            "--question",
            "上下游衝擊",
            "--json",
        ],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "company_filing_render_smoke": {
        "id": "company_filing_render_smoke",
        "label": "Company filing render smoke",
        "description": "驗證 Browserless / Playwright / proxy fallback 可解析一般 HTML。",
        "display_command": (
            ".venv/bin/python scripts/company_filing_render_smoke.py "
            "--url https://example.com/ --json"
        ),
        "argv": [
            sys.executable,
            "scripts/company_filing_render_smoke.py",
            "--url",
            "https://example.com/",
            "--json",
        ],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "high_risk_unlocker_smoke": {
        "id": "high_risk_unlocker_smoke",
        "label": "High-risk MOPS unlocker smoke",
        "description": "驗證 FlareSolverr / unlocker provider 是否可處理 MOPS 高風險入口。",
        "display_command": (
            ".venv/bin/python scripts/company_filing_render_smoke.py "
            "--url https://mops.twse.com.tw/ --json"
        ),
        "argv": [
            sys.executable,
            "scripts/company_filing_render_smoke.py",
            "--url",
            "https://mops.twse.com.tw/",
            "--json",
        ],
        "timeout_seconds": 120,
        "read_only": True,
    },
}


def maintenance_diagnostic_action_catalog() -> dict:
    return {
        "collector_path": "app/services/maintenance_diagnostics.py",
        "execution_policy": "allowlisted_read_only_subprocess",
        "actions": [
            _action_catalog_row(action)
            for action in sorted(
                MAINTENANCE_DIAGNOSTIC_ACTIONS.values(),
                key=lambda item: str(item["id"]),
            )
        ],
    }


def run_maintenance_diagnostic_action(action_id: str, *, root: Path | None = None) -> dict:
    action = MAINTENANCE_DIAGNOSTIC_ACTIONS.get(str(action_id or ""))
    if not action:
        raise ValueError(f"Unknown maintenance diagnostic action: {action_id}")
    if not action.get("read_only"):
        raise ValueError(f"Maintenance diagnostic action is not read-only: {action_id}")
    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            [str(part) for part in action["argv"]],
            cwd=root or PROJECT_ROOT,
            check=False,
            text=True,
            capture_output=True,
            timeout=int(action["timeout_seconds"]),
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started_at
        return {
            **_action_catalog_row(action),
            "status": "timeout",
            "returncode": None,
            "duration_seconds": round(elapsed, 3),
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
            "message": f"診斷逾時：{int(action['timeout_seconds'])}s",
        }
    elapsed = time.monotonic() - started_at
    return {
        **_action_catalog_row(action),
        "status": "success" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "duration_seconds": round(elapsed, 3),
        "stdout_tail": _tail_text(completed.stdout),
        "stderr_tail": _tail_text(completed.stderr),
        "message": "診斷完成" if completed.returncode == 0 else "診斷回傳非 0 結束碼",
    }


def _action_catalog_row(action: dict) -> dict:
    return {
        "id": str(action["id"]),
        "label": str(action["label"]),
        "description": str(action["description"]),
        "display_command": str(action["display_command"]),
        "timeout_seconds": int(action["timeout_seconds"]),
        "read_only": bool(action["read_only"]),
    }


def _tail_text(value: object) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-MAX_OUTPUT_CHARS:]
