from __future__ import annotations

import sys


MAINTENANCE_DIAGNOSTIC_ACTIONS = {
    "upgrade_audit": {
        "id": "upgrade_audit",
        "label": "Upgrade audit",
        "description": "檢查核心升級能力與外部部署選配狀態，並自動套用已啟動的本機依賴預設值。",
        "display_command": (
            ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
        ),
        "argv": [
            sys.executable,
            "scripts/upgrade_audit.py",
            "--auto-local-defaults",
            "--json",
        ],
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
            "--env-check --env-check-target all --env-file .env --json"
        ),
        "argv": [
            sys.executable,
            "scripts/external_deployment_env_gaps.py",
            "--env-check",
            "--env-check-target",
            "all",
            "--env-file",
            ".env",
            "--json",
        ],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "llm_quota_env_audit": {
        "id": "llm_quota_env_audit",
        "label": "LLM quota env audit",
        "description": (
            "檢查 .env 的 LLM_MODEL_DAILY_REQUEST_BUDGETS 是否符合追蹤中的 "
            "Free Tier / AI Studio 參考額度，不顯示密鑰。"
        ),
        "display_command": (
            ".venv/bin/python scripts/llm_quota_env_audit.py --env-file .env --json"
        ),
        "argv": [
            sys.executable,
            "scripts/llm_quota_env_audit.py",
            "--env-file",
            ".env",
            "--json",
        ],
        "timeout_seconds": 30,
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
    "task_submission_smoke": {
        "id": "task_submission_smoke",
        "label": "Task submission readiness smoke",
        "description": (
            "只讀檢查 /services/runtime-identity、/services/status 的 task_queue readiness "
            "與背景任務提交 smoke 指令，不送出 Celery 任務。"
        ),
        "display_command": ".venv/bin/python scripts/task_submission_smoke.py --json",
        "argv": [sys.executable, "scripts/task_submission_smoke.py", "--json"],
        "timeout_seconds": 30,
        "read_only": True,
    },
    "task_submission_noop_smoke": {
        "id": "task_submission_noop_smoke",
        "label": "Task submission no-op submit smoke",
        "description": (
            "送出 smoke=true 的 no-op market_refresh，驗證 /tasks/data-operation、"
            "Celery enqueue 與 task wiring；不呼叫外部市場資料 API。完整 submit/wait "
            "smoke 請從 CLI 執行，避免單 worker 診斷任務自我等待。"
        ),
        "display_command": (
            ".venv/bin/python scripts/task_submission_smoke.py "
            "--submit --timeout 10 --skip-processing-ready --json"
        ),
        "argv": [
            sys.executable,
            "scripts/task_submission_smoke.py",
            "--submit",
            "--timeout",
            "10",
            "--skip-processing-ready",
            "--json",
        ],
        "timeout_seconds": 45,
        "read_only": False,
        "effect": "safe_noop_task_submission",
        "safe_to_run": True,
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
    "local_chroma_upgrade_audit": {
        "id": "local_chroma_upgrade_audit",
        "label": "Local Chroma upgrade audit",
        "description": "套用本機 Chroma 預設值後檢查 RAG / vector store integration 狀態。",
        "display_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-chroma-defaults --wait-local-chroma 20 --json"
        ),
        "argv": [
            sys.executable,
            "scripts/upgrade_audit.py",
            "--local-chroma-defaults",
            "--wait-local-chroma",
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
    "graphrag_import_first_smoke": {
        "id": "graphrag_import_first_smoke",
        "label": "GraphRAG import-first smoke",
        "description": (
            "先將 bundled supply-chain graph payload 匯入目前設定的本機 Neo4j，"
            "再驗證 guarded live Cypher query。"
        ),
        "display_command": (
            ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
            "--local-neo4j-defaults "
            "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 "
            "--import-first --json"
        ),
        "argv": [
            sys.executable,
            "scripts/neo4j_graphrag_smoke.py",
            "--local-neo4j-defaults",
            "--tickers",
            "2330",
            "--target-ticker",
            "2382",
            "--question",
            "上下游衝擊",
            "--import-first",
            "--json",
        ],
        "timeout_seconds": 120,
        "read_only": False,
        "effect": "safe_local_neo4j_import_smoke",
        "safe_to_run": True,
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
    "structured_company_filing_sample_contract_smoke": {
        "id": "structured_company_filing_sample_contract_smoke",
        "label": "Structured filing sample contract smoke",
        "description": "用 bundled sample JSON 驗證 TEJ/資料商結構化公司文件 API contract，不連外。",
        "display_command": (
            ".venv/bin/python scripts/structured_company_filing_smoke.py "
            "--sample-json examples/structured_company_filing_sample.json "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation "
            "--json --strict"
        ),
        "argv": [
            sys.executable,
            "scripts/structured_company_filing_smoke.py",
            "--sample-json",
            "examples/structured_company_filing_sample.json",
            "--ticker",
            "2330",
            "--company-name",
            "台積電",
            "--document-type",
            "investor_presentation",
            "--json",
            "--strict",
        ],
        "timeout_seconds": 60,
        "read_only": True,
    },
    "structured_company_filing_fixture_http_smoke": {
        "id": "structured_company_filing_fixture_http_smoke",
        "label": "Structured filing fixture HTTP smoke",
        "description": "臨時啟動本機 fixture 並跑 live HTTP fetch path，不連外且不需要 token。",
        "display_command": (
            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
            "--json --strict"
        ),
        "argv": [
            sys.executable,
            "scripts/structured_company_filing_fixture_smoke.py",
            "--json",
            "--strict",
        ],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "structured_company_filing_provider_profile_fixture_smoke": {
        "id": "structured_company_filing_provider_profile_fixture_smoke",
        "label": "Structured filing TEJ profile fixture smoke",
        "description": (
            "用本機 fixture 驗證 TEJ provider profile 的 Bearer auth、"
            "document_type 參數與 JSON 轉換，不連外且不需要真實 token。"
        ),
        "display_command": (
            ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
            "--provider-profile tej --json --strict"
        ),
        "argv": [
            sys.executable,
            "scripts/structured_company_filing_fixture_smoke.py",
            "--provider-profile",
            "tej",
            "--json",
            "--strict",
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
            "--local-browser-render-defaults --prefer-unlocker "
            "--url https://mops.twse.com.tw/ --json"
        ),
        "argv": [
            sys.executable,
            "scripts/company_filing_render_smoke.py",
            "--local-browser-render-defaults",
            "--prefer-unlocker",
            "--url",
            "https://mops.twse.com.tw/",
            "--json",
        ],
        "timeout_seconds": 120,
        "read_only": True,
    },
}


def maintenance_diagnostic_action_row(action: dict) -> dict:
    effect = str(
        action.get("effect")
        or ("read_only" if action.get("read_only") else "disabled")
    )
    return {
        "id": str(action["id"]),
        "label": str(action["label"]),
        "description": str(action["description"]),
        "display_command": str(action["display_command"]),
        "timeout_seconds": int(action["timeout_seconds"]),
        "read_only": bool(action["read_only"]),
        "effect": effect,
        "safe_to_run": maintenance_diagnostic_action_safe_to_run(action),
    }


def maintenance_diagnostic_action_safe_to_run(action: dict) -> bool:
    return bool(
        action.get("read_only")
        or (
            action.get("safe_to_run")
            and str(action.get("effect") or "")
            in {
                "safe_local_neo4j_import_smoke",
                "safe_noop_task_submission",
            }
        )
    )


__all__ = [
    "MAINTENANCE_DIAGNOSTIC_ACTIONS",
    "maintenance_diagnostic_action_row",
    "maintenance_diagnostic_action_safe_to_run",
]
