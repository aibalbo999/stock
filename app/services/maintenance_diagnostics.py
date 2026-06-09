from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_OUTPUT_CHARS = 4000
MAX_SUMMARY_ROWS = 8
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
            "summary_rows": _diagnostic_summary_rows(str(action["id"]), exc.stdout),
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
        "summary_rows": _diagnostic_summary_rows(str(action["id"]), completed.stdout),
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


def _diagnostic_summary_rows(action_id: str, stdout: object) -> list[dict]:
    payload = _json_object_from_stdout(stdout)
    if not payload:
        return []
    if action_id in {
        "upgrade_audit",
        "local_neo4j_upgrade_audit",
        "local_unlocker_upgrade_audit",
    }:
        return _upgrade_audit_summary_rows(payload)
    if action_id == "external_integrations_smoke":
        return _external_integrations_summary_rows(payload)
    if action_id == "external_deployment_env_gaps":
        return _external_env_gap_summary_rows(payload)
    if action_id == "external_deployment_env_check":
        return _external_env_check_summary_rows(payload)
    if action_id == "neo4j_payload_dry_run":
        return _neo4j_payload_summary_rows(payload)
    if action_id in {"graphrag_local_contract_smoke", "graphrag_live_query_smoke"}:
        return _graphrag_smoke_summary_rows(payload)
    if action_id in {"company_filing_render_smoke", "high_risk_unlocker_smoke"}:
        return _company_filing_render_summary_rows(payload)
    if action_id == "structured_company_filing_sample_contract_smoke":
        return _structured_company_filing_smoke_summary_rows(payload)
    if action_id == "task_submission_smoke":
        return _task_submission_smoke_summary_rows(payload)
    return _generic_json_summary_rows(payload)


def _json_object_from_stdout(value: object) -> dict:
    if value is None:
        return {}
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    text = text.strip()
    if not text:
        return {}
    for candidate in (text, _json_object_slice(text)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _json_object_slice(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start : end + 1]


def _upgrade_audit_summary_rows(payload: dict) -> list[dict]:
    summary = _dict_value(payload, "summary")
    rows = [
        _summary_row(
            "Upgrade audit",
            payload.get("overall_status") or "-",
            _ready_count(summary.get("ready"), summary.get("total_checks")),
            _counts(
                warnings=summary.get("total_warnings"),
                optional=summary.get("optional_warnings"),
                failures=summary.get("failures"),
            ),
            _deployment_note(payload, summary),
        )
    ]
    enablement = _dict_value(payload, "external_deployment_enablement")
    if enablement:
        rows.append(_enablement_summary_row(enablement))
    gap_counts = _dict_value(payload, "external_deployment_pending_gap_action_counts")
    if gap_counts:
        rows.append(_pending_gap_action_summary_row(gap_counts))
    warnings = _list_value(payload, "all_warnings") or _list_value(payload, "warnings")
    rows.extend(_warning_rows(warnings))
    return rows[:MAX_SUMMARY_ROWS]


def _external_integrations_summary_rows(payload: dict) -> list[dict]:
    rows = [
        _summary_row(
            "External integrations smoke",
            payload.get("status") or "-",
            _ready_count(payload.get("ready_count"), payload.get("check_count")),
            _counts(actionable=payload.get("actionable_check_count")),
            _shorten(payload.get("strict_command") or "-"),
        )
    ]
    enablement = _dict_value(payload, "enablement_summary")
    if enablement:
        rows.append(_enablement_summary_row(enablement))
    gap_counts = _dict_value(payload, "pending_gap_action_counts")
    if gap_counts:
        rows.append(_pending_gap_action_summary_row(gap_counts))
    checks = [
        item
        for item in _list_value(payload, "checks")
        if isinstance(item, dict) and str(item.get("status") or "") != "ready"
    ]
    rows.extend(_warning_rows(checks))
    return rows[:MAX_SUMMARY_ROWS]


def _external_env_gap_summary_rows(payload: dict) -> list[dict]:
    rows = [
        _summary_row(
            "External env gaps",
            payload.get("status") or "-",
            _counts(local=payload.get("local_action_count"), manual=payload.get("manual_secret_count")),
            _counts(missing=payload.get("missing_count"), capabilities=payload.get("capability_gap_count")),
            payload.get("local_unlocker_start_command")
            or payload.get("local_start_command")
            or "-",
        )
    ]
    for row in _list_value(payload, "resolution_rows"):
        if not isinstance(row, dict):
            continue
        rows.append(
            _summary_row(
                str(row.get("能力") or "-"),
                str(row.get("處理策略") or row.get("優先級") or "-"),
                _counts(local=row.get("本機可套用"), manual=row.get("需人工處理")),
                _counts(missing=row.get("缺少"), gaps=row.get("缺口數")),
                row.get("本機指令") or row.get("建議動作") or "-",
            )
        )
    return rows[:MAX_SUMMARY_ROWS]


def _external_env_check_summary_rows(payload: dict) -> list[dict]:
    checks = _dict_value(payload, "checks")
    rows = [
        _summary_row(
            "External env check",
            payload.get("status") or "-",
            _counts(target=payload.get("target"), gaps=payload.get("gap_count")),
            _counts(targets=len(checks), env_file=payload.get("env_file")),
            "補齊 missing；確認 different；密鑰只顯示是否已設定。",
        )
    ]
    if checks:
        for target in payload.get("targets") or sorted(checks):
            check = checks.get(str(target)) if isinstance(checks, dict) else None
            if not isinstance(check, dict):
                continue
            rows.append(_external_env_check_target_summary_row(check))
    else:
        rows.append(_external_env_check_target_summary_row(payload))
    return rows[:MAX_SUMMARY_ROWS]


def _external_env_check_target_summary_row(check: dict) -> dict:
    return _summary_row(
        f"{check.get('target') or '-'} env",
        check.get("status") or "-",
        _ready_count(check.get("set_count"), check.get("checked_count")),
        _counts(
            missing=check.get("missing_count"),
            different=check.get("different_count"),
            env_exists=check.get("env_file_exists"),
        ),
        _external_env_check_next_action(check),
    )


def _external_env_check_next_action(check: dict) -> str:
    rows = _list_value(check, "rows")
    for status in ("missing", "different"):
        row = next(
            (
                item
                for item in rows
                if isinstance(item, dict) and str(item.get("status") or "") == status
            ),
            {},
        )
        if row:
            return row.get("action") or row.get("env_key") or "-"
    return "目前 target 的外部部署 env 已可用。"


def _neo4j_payload_summary_rows(payload: dict) -> list[dict]:
    graph_payload = _dict_value(payload, "payload")
    parameters = _dict_value(graph_payload, "parameters")
    return [
        _summary_row(
            "Neo4j payload dry-run",
            payload.get("status") or "-",
            str(graph_payload.get("format") or "-"),
            _counts(
                nodes=len(_list_value(parameters, "nodes")),
                structural=len(_list_value(parameters, "structural_edges")),
                peers=len(_list_value(parameters, "peer_edges")),
                statements=len(_list_value(graph_payload, "statements")),
            ),
            _shorten(_dict_value(graph_payload, "query_examples").get("shortest_path_between_companies") or "-"),
        )
    ]


def _graphrag_smoke_summary_rows(payload: dict) -> list[dict]:
    graph_payload = _dict_value(payload, "payload")
    query_result = _dict_value(payload, "query_result")
    local_dry_run = _dict_value(query_result, "local_dry_run")
    plan = _dict_value(query_result, "plan")
    rows = [
        _summary_row(
            "GraphRAG smoke",
            payload.get("status") or "-",
            _yes_no(payload.get("ready")),
            _counts(
                import_first=payload.get("import_first"),
                local_contract=payload.get("local_contract"),
            ),
            plan.get("intent") or payload.get("smoke_command") or "-",
        ),
        _summary_row(
            "Neo4j payload",
            graph_payload.get("format") or "-",
            _yes_no(graph_payload.get("ready")),
            _counts(
                nodes=graph_payload.get("node_count"),
                structural=graph_payload.get("structural_edge_count"),
                peers=graph_payload.get("peer_edge_count"),
                statements=graph_payload.get("statement_count"),
            ),
            "-",
        ),
    ]
    if local_dry_run:
        rows.append(
            _summary_row(
                "Cypher query",
                local_dry_run.get("status") or "-",
                _yes_no(local_dry_run.get("ready")),
                _counts(rows=local_dry_run.get("row_count")),
                _shorten(plan.get("cypher") or "-"),
            )
        )
    return rows[:MAX_SUMMARY_ROWS]


def _company_filing_render_summary_rows(payload: dict) -> list[dict]:
    attempts = _list_value(payload, "attempts")
    rows = [
        _summary_row(
            "Company filing render",
            payload.get("status") or "-",
            _yes_no(payload.get("ready")),
            _counts(attempts=len(attempts), proxies=payload.get("proxy_count")),
            payload.get("url") or payload.get("smoke_command") or "-",
        )
    ]
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        document = _dict_value(attempt, "document")
        rows.append(
            _summary_row(
                str(attempt.get("provider") or attempt.get("kind") or "-"),
                str(attempt.get("kind") or "-"),
                _yes_no(attempt.get("ready")),
                _counts(text=document.get("text_length"), min=attempt.get("min_text_chars")),
                document.get("title") or attempt.get("fallback_reason") or "-",
            )
        )
    runtime = _dict_value(payload, "browser_render_runtime")
    if runtime and not runtime.get("configuration_ready"):
        rows.append(
            _summary_row(
                "Browser render config",
                _dict_value(runtime, "configuration_check").get("status") or "disabled",
                _yes_no(runtime.get("configuration_ready")),
                str(runtime.get("provider") or "-"),
                runtime.get("fallback_reason") or "-",
            )
        )
    return rows[:MAX_SUMMARY_ROWS]


def _structured_company_filing_smoke_summary_rows(payload: dict) -> list[dict]:
    rows = [
        _summary_row(
            "Structured filing contract",
            payload.get("status") or "-",
            _yes_no(payload.get("ready")),
            _counts(
                rows=payload.get("raw_row_count"),
                documents=payload.get("document_count"),
                errors=payload.get("error_count"),
            ),
            payload.get("sample_path") or payload.get("smoke_command") or "-",
        )
    ]
    runtime = _dict_value(payload, "runtime")
    if runtime:
        rows.append(
            _summary_row(
                "Structured API runtime",
                "configured" if runtime.get("configured") else "not_configured",
                str(runtime.get("provider") or "-"),
                _counts(
                    url=runtime.get("url_configured"),
                    token=runtime.get("token_configured"),
                ),
                runtime.get("fallback_reason") or "-",
            )
        )
    request = _dict_value(payload, "request")
    if request:
        rows.append(
            _summary_row(
                "Structured API request",
                str(request.get("ticker") or "-"),
                str(request.get("company_name") or "-"),
                ",".join(str(item) for item in request.get("document_types") or []) or "-",
                _counts(limit=request.get("limit")),
            )
        )
    for document in _list_value(payload, "documents"):
        if not isinstance(document, dict):
            continue
        rows.append(
            _summary_row(
                document.get("title") or "Document sample",
                document.get("document_type") or "-",
                document.get("ticker") or "-",
                _counts(text=document.get("text_length")),
                document.get("url") or document.get("publisher") or "-",
            )
        )
    for error in _list_value(payload, "errors"):
        if not isinstance(error, dict):
            continue
        rows.append(
            _summary_row(
                "Structured API row error",
                error.get("category") or "-",
                error.get("row_index") if "row_index" in error else "-",
                ",".join(str(item) for item in error.get("required_fields") or []) or "-",
                error.get("message") or payload.get("remediation") or "-",
            )
        )
    return rows[:MAX_SUMMARY_ROWS]


def _task_submission_smoke_summary_rows(payload: dict) -> list[dict]:
    checks = _list_value(payload, "checks")
    failed_checks = sum(
        1
        for item in checks
        if isinstance(item, dict) and str(item.get("status") or "") == "failed"
    )
    warning_checks = sum(
        1
        for item in checks
        if isinstance(item, dict) and str(item.get("status") or "") == "warning"
    )
    rows = [
        _summary_row(
            "Task submission smoke",
            payload.get("status") or "-",
            _counts(submit=payload.get("submit"), wait=payload.get("wait")),
            _counts(failed=failed_checks, warnings=warning_checks),
            _first_text(payload, "next_actions") or "背景任務提交 readiness 正常。",
        )
    ]
    runtime_identity = _dict_value(payload, "runtime_identity")
    if runtime_identity:
        rows.append(
            _summary_row(
                "API runtime identity",
                runtime_identity.get("status") or "-",
                runtime_identity.get("expected_commit_short") or "-",
                runtime_identity.get("actual_commit_short") or "-",
                runtime_identity.get("reason") or runtime_identity.get("error") or "-",
            )
        )
    task_queue = _dict_value(payload, "task_queue")
    if task_queue:
        rows.append(
            _summary_row(
                "Task queue",
                "ready" if task_queue.get("ready") else "not_ready",
                _counts(
                    processing=task_queue.get("processing_ready"),
                    worker=task_queue.get("worker_online"),
                ),
                _counts(legacy_status_shape=task_queue.get("legacy_status_shape")),
                task_queue.get("status_shape_warning") or "-",
            )
        )
    submission = _dict_value(payload, "submission")
    if submission:
        body = _dict_value(submission, "json")
        rows.append(
            _summary_row(
                "Data operation submission",
                "ok" if submission.get("ok") else "failed",
                submission.get("status_code") or "-",
                body.get("task_id") or submission.get("error") or "-",
                submission.get("url") or "-",
            )
        )
    task_poll = _dict_value(payload, "task_poll")
    if task_poll:
        rows.append(
            _summary_row(
                "Task polling",
                task_poll.get("status") or "-",
                _counts(
                    ready=task_poll.get("ready"),
                    successful=task_poll.get("successful"),
                ),
                task_poll.get("task_status") or "-",
                _first_text(task_poll, "poll_errors") or "-",
            )
        )
    return rows[:MAX_SUMMARY_ROWS]


def _generic_json_summary_rows(payload: dict) -> list[dict]:
    return [
        _summary_row(
            "JSON output",
            payload.get("status") or "-",
            _yes_no(payload.get("ready")) if "ready" in payload else "-",
            _counts(keys=len(payload)),
            "-",
        )
    ]


def _warning_rows(items: list[object]) -> list[dict]:
    rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        enablement = _dict_value(item, "enablement_profile")
        rows.append(
            _summary_row(
                item.get("label") or item.get("capability") or "-",
                item.get("status") or item.get("severity") or "-",
                _yes_no(item.get("ready")) if "ready" in item else "-",
                enablement.get("group_label") or item.get("area") or "-",
                item.get("remediation") or enablement.get("recommended_path") or "-",
            )
        )
    return rows


def _enablement_summary_row(enablement: dict) -> dict:
    return _summary_row(
        "外部部署啟用",
        _counts(pending=enablement.get("pending"), ready=enablement.get("ready")),
        _counts(
            free_local=enablement.get("free_local_pending"),
            local_actions=enablement.get("local_action_available"),
        ),
        _counts(
            quota=enablement.get("quota_or_external_pending"),
            paid=enablement.get("paid_external_pending"),
        ),
        enablement.get("primary_next_action") or "-",
    )


def _pending_gap_action_summary_row(counts: dict) -> dict:
    local_action = int(counts.get("local_action") or 0)
    quota_or_external = int(counts.get("quota_or_external") or 0)
    paid_external = int(counts.get("paid_external") or 0)
    manual_configuration = int(counts.get("manual_configuration") or 0)
    return _summary_row(
        "外部缺口處理類型",
        _counts(
            local_action=local_action,
            quota_or_external=quota_or_external,
        ),
        _counts(
            local=local_action,
            manual=manual_configuration,
        ),
        _counts(
            paid=paid_external,
            manual=manual_configuration,
        ),
        _pending_gap_next_action(
            local_action=local_action,
            quota_or_external=quota_or_external,
            paid_external=paid_external,
            manual_configuration=manual_configuration,
        ),
    )


def _pending_gap_next_action(
    *,
    local_action: int,
    quota_or_external: int,
    paid_external: int,
    manual_configuration: int,
) -> str:
    if local_action:
        return "先執行本機啟動/驗證指令，再重跑 audit 或 smoke。"
    if paid_external:
        return "剩餘缺口需要外部資料 API 或服務合約。"
    if quota_or_external:
        return "剩餘缺口主要取決於 API 額度或外部模型設定。"
    if manual_configuration:
        return "依各項 remediation 手動補齊設定。"
    return "目前沒有待處理外部缺口。"


def _summary_row(item: object, status: object, ready: object, counts: object, next_step: object) -> dict:
    return {
        "項目": _shorten(item, limit=52),
        "狀態": _shorten(status, limit=48),
        "Ready": _shorten(ready, limit=36),
        "數量": _shorten(counts, limit=64),
        "下一步": _shorten(next_step, limit=140),
    }


def _deployment_note(payload: dict, summary: dict) -> str:
    note = _counts(
        implementation=summary.get("implementation_status") or payload.get("implementation_status"),
        deployment=summary.get("deployment_status") or payload.get("deployment_status"),
        blocking=summary.get("deployment_blocking_status")
        or payload.get("deployment_blocking_status"),
    )
    if summary.get("deployment_optional_only") or payload.get("deployment_optional_only"):
        return f"{note}; optional_external_only=True"
    return note


def _ready_count(ready: object, total: object) -> str:
    if ready is None and total is None:
        return "-"
    if total is None:
        return str(ready)
    return f"{ready or 0}/{total or 0}"


def _counts(**values: object) -> str:
    parts = [
        f"{key}={value}"
        for key, value in values.items()
        if value is not None and value != ""
    ]
    return "；".join(parts) if parts else "-"


def _yes_no(value: object) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    if value is None:
        return "-"
    return str(value)


def _dict_value(payload: dict, key: str) -> dict:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _list_value(payload: dict, key: str) -> list:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _first_text(payload: dict, key: str) -> str:
    values = _list_value(payload, key)
    return str(values[0]) if values else ""


def _shorten(value: object, *, limit: int = 120) -> str:
    text = str(value if value is not None else "-").replace("\n", " ").strip()
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"
