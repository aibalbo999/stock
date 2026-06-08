from __future__ import annotations

import time
from pathlib import Path

from scripts import start_system as startup


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEPENDENCY_WAIT_SECONDS = 10
MAINTENANCE_OPERATIONS = {
    "start_local_dependencies": {
        "id": "start_local_dependencies",
        "label": "啟動本機核心依賴",
        "description": "啟動 Redis、Postgres、Neo4j、Browserless 與 Chroma，並等待本機 ports。",
        "display_command": "docker compose up -d redis postgres neo4j browserless chroma",
        "timeout_seconds": 240,
        "requires_confirmation": True,
        "mutates_local_state": True,
        "scope": "Docker services and current API process env defaults",
        "include_unlocker": False,
        "wait_seconds": DEFAULT_DEPENDENCY_WAIT_SECONDS,
    },
    "start_local_dependencies_with_unlocker": {
        "id": "start_local_dependencies_with_unlocker",
        "label": "啟動本機依賴與 unlocker",
        "description": (
            "啟動核心依賴與 FlareSolverr，並在目前 API 程序優先套用 unlocker render provider。"
        ),
        "display_command": (
            "docker compose --profile unlocker up -d redis postgres neo4j browserless chroma flaresolverr"
        ),
        "timeout_seconds": 260,
        "requires_confirmation": True,
        "mutates_local_state": True,
        "scope": "Docker services and current API process env defaults",
        "include_unlocker": True,
        "wait_seconds": DEFAULT_DEPENDENCY_WAIT_SECONDS,
    },
}


POST_RUN_CHECKS = {
    "start_local_dependencies": (
        {
            "item": "Neo4j / GraphRAG 本機設定稽核",
            "purpose": "確認目前程序套用本機 Neo4j env 後，live import 與 guarded Cypher 狀態。",
            "diagnostic_action_id": "local_neo4j_upgrade_audit",
            "command": (
                ".venv/bin/python scripts/upgrade_audit.py "
                "--local-neo4j-defaults --wait-local-neo4j 20 --json"
            ),
        },
        {
            "item": "Neo4j payload dry-run",
            "purpose": "確認 Neo4j 匯入 payload contract 仍可生成。",
            "diagnostic_action_id": "neo4j_payload_dry_run",
            "command": ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run",
        },
        {
            "item": "GraphRAG local Cypher contract",
            "purpose": "確認 guarded Cypher planner 與本機 dry-run 邏輯。",
            "diagnostic_action_id": "graphrag_local_contract_smoke",
            "command": (
                ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 "
                "--local-contract --json"
            ),
        },
        {
            "item": "GraphRAG live Neo4j smoke",
            "purpose": "Neo4j env 套用後，驗證 live query / import-first 路徑。",
            "diagnostic_action_id": "",
            "command": (
                ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 "
                "--import-first --json"
            ),
        },
        {
            "item": "公司文件 render fallback smoke",
            "purpose": "確認 Browserless 或 Playwright 後援可解析一般 HTML。",
            "diagnostic_action_id": "company_filing_render_smoke",
            "command": (
                ".venv/bin/python scripts/company_filing_render_smoke.py "
                "--url https://example.com/ --json"
            ),
        },
    ),
    "start_local_dependencies_with_unlocker": (
        {
            "item": "Neo4j / GraphRAG / FlareSolverr 本機設定稽核",
            "purpose": "確認本機 Neo4j 與 FlareSolverr env 套用後的外部選配狀態。",
            "diagnostic_action_id": "local_unlocker_upgrade_audit",
            "command": (
                ".venv/bin/python scripts/upgrade_audit.py "
                "--local-neo4j-defaults --prefer-unlocker "
                "--wait-local-neo4j 20 --wait-local-flaresolverr 20 "
                "--local-browser-render-defaults --json"
            ),
        },
        {
            "item": "高風險 MOPS unlocker smoke",
            "purpose": "確認 FlareSolverr / unlocker provider 可處理 MOPS 高風險入口。",
            "diagnostic_action_id": "high_risk_unlocker_smoke",
            "command": (
                ".venv/bin/python scripts/company_filing_render_smoke.py "
                "--url https://mops.twse.com.tw/ --json"
            ),
        },
    ),
}


def maintenance_operation_catalog() -> dict:
    return {
        "collector_path": "app/services/maintenance_operations.py",
        "execution_policy": "allowlisted_local_dependency_operations",
        "operations": [
            _operation_catalog_row(operation)
            for operation in sorted(
                MAINTENANCE_OPERATIONS.values(),
                key=lambda item: str(item["id"]),
            )
        ],
    }


def run_maintenance_operation(
    action_id: str,
    *,
    confirmed: bool = False,
    root: Path | None = None,
) -> dict:
    operation = MAINTENANCE_OPERATIONS.get(str(action_id or ""))
    if not operation:
        raise ValueError(f"Unknown maintenance operation: {action_id}")
    if operation.get("requires_confirmation") and not confirmed:
        raise PermissionError(f"Maintenance operation requires confirmation: {action_id}")
    if not operation.get("mutates_local_state"):
        raise ValueError(
            f"Maintenance operation is not marked as local-state mutating: {action_id}"
        )
    started_at = time.monotonic()
    try:
        result = _run_local_dependency_start(operation, root=root or PROJECT_ROOT)
    except Exception as exc:  # pragma: no cover - defensive boundary for API response hygiene
        elapsed = time.monotonic() - started_at
        return {
            **_operation_catalog_row(operation),
            "status": "failed",
            "duration_seconds": round(elapsed, 3),
            "message": f"維護操作失敗：{exc}",
            "dependency_status": {},
            "wait": {},
            "wait_lines": [],
            "start_record": {},
            "applied_env_keys": [],
        }
    elapsed = time.monotonic() - started_at
    return {
        **_operation_catalog_row(operation),
        **result,
        "post_run_checks": post_run_checks_for_operation(str(operation["id"])),
        "duration_seconds": round(elapsed, 3),
    }


def _run_local_dependency_start(operation: dict, *, root: Path) -> dict:
    include_unlocker = bool(operation.get("include_unlocker"))
    wait_seconds = max(0, int(operation.get("wait_seconds") or DEFAULT_DEPENDENCY_WAIT_SECONDS))
    local_dependency_env = startup.apply_local_dependency_env_defaults(
        enable_browser_render=True,
        enable_chroma=True,
        prefer_browserless=not include_unlocker,
        prefer_unlocker=include_unlocker,
    )
    dependency_status = startup.start_dependency_services(
        root,
        allow_pull_missing_images=False,
        include_unlocker=include_unlocker,
    )
    dependency_wait_status = startup.wait_for_local_dependency_ports(
        dependency_status,
        local_dependency_env,
        timeout_seconds=wait_seconds,
    )
    switch_status = startup.fallback_local_browser_render_to_playwright(
        local_dependency_env,
        dependency_status,
        dependency_wait_status,
    )
    if switch_status:
        dependency_wait_status["browser_render_fallback"] = switch_status
    start_record = startup.write_local_dependency_start_status(
        root,
        dependency_status,
        dependency_wait_status,
        local_dependency_env,
        include_unlocker=include_unlocker,
        wait_seconds=wait_seconds,
    )
    return {
        "status": _operation_result_status(dependency_status, dependency_wait_status),
        "message": str(dependency_status.get("message") or ""),
        "dependency_status": dependency_status,
        "wait": dependency_wait_status,
        "wait_lines": startup.dependency_wait_status_lines(dependency_wait_status),
        "start_record": start_record,
        "applied_env_keys": sorted(str(key) for key in local_dependency_env),
    }


def _operation_result_status(dependency_status: dict, wait_status: dict) -> str:
    if startup.dependency_start_blocker(dependency_status):
        if dependency_status.get("status") == "需下載":
            return "needs_download"
        return "failed"
    if dependency_status.get("status") == "略過":
        return "skipped"
    if dependency_status.get("status") != "已啟動":
        return "failed"
    bool_wait_values = [value for value in wait_status.values() if isinstance(value, bool)]
    if bool_wait_values and not all(bool_wait_values):
        return "partial"
    return "success"


def _operation_catalog_row(operation: dict) -> dict:
    return {
        "id": str(operation["id"]),
        "label": str(operation["label"]),
        "description": str(operation["description"]),
        "display_command": str(operation["display_command"]),
        "timeout_seconds": int(operation["timeout_seconds"]),
        "requires_confirmation": bool(operation["requires_confirmation"]),
        "mutates_local_state": bool(operation["mutates_local_state"]),
        "scope": str(operation["scope"]),
        "post_run_checks": post_run_checks_for_operation(str(operation["id"])),
    }


def post_run_checks_for_operation(action_id: str) -> list[dict]:
    checks = list(POST_RUN_CHECKS.get(str(action_id or ""), ()))
    if action_id == "start_local_dependencies_with_unlocker":
        checks = [
            *POST_RUN_CHECKS["start_local_dependencies"],
            *checks,
        ]
    return [
        {
            "item": str(check["item"]),
            "purpose": str(check["purpose"]),
            "diagnostic_action_id": str(check.get("diagnostic_action_id") or ""),
            "command": str(check["command"]),
        }
        for check in checks
    ]
