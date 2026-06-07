from __future__ import annotations

from html import escape

from app.services.candidate_confidence import format_confidence_score

_EXTERNAL_SMOKE_COMMAND_KEYS = frozenset(
    {
        "smoke_cli",
        "smoke_command",
        "smoke_commands",
        "sample_contract_cli",
        "payload_dry_run_cli",
        "import_smoke_cli",
        "neo4j_graphrag_smoke_command",
        "company_filing_render_smoke_command",
        "structured_company_filing_smoke_command",
    }
)
_EXTERNAL_DETAIL_KEYS = frozenset(
    {
        "fallback_reason",
        "connection_error",
        "runtime_error",
        "error",
        "reason",
    }
)


def maintenance_service_metrics(status: dict, service_snapshot: dict) -> dict:
    confidence = service_snapshot.get("candidate_confidence") or {}
    high_threshold = confidence.get("high_threshold")
    task_queue = service_snapshot.get("task_queue") or {}
    return {
        "資料庫": "正常" if status.get("integrity", {}).get("ok", True) else "異常",
        "Redis": "正常" if service_snapshot.get("redis", {}).get("ok") else "未連線",
        "背景任務": _task_queue_label(task_queue),
        "AI Key": service_snapshot.get("gemini", {}).get("key_count", 0),
        "市場資料": "可用" if service_snapshot.get("finmind", {}).get("mode") else "檢查",
        "升格門檻": format_confidence_score(float(high_threshold)) if high_threshold is not None else "未評估",
    }


def _task_queue_label(task_queue: dict) -> str:
    if not task_queue.get("ready"):
        return "檢查"
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return "可排隊"
    return "可送出"


def task_queue_health_rows(service_snapshot: dict) -> list[dict]:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    return [
        {
            "項目": "Queue 提交",
            "狀態": _task_queue_label(task_queue),
            "說明": _task_queue_submission_detail(task_queue),
        },
        {
            "項目": "Redis Broker",
            "狀態": _ok_label(task_queue.get("broker_ok")),
            "說明": _connection_detail(task_queue, "broker_url"),
        },
        {
            "項目": "Redis Backend",
            "狀態": _ok_label(task_queue.get("backend_ok")),
            "說明": _connection_detail(task_queue, "backend_url"),
        },
        {
            "項目": "Task wiring",
            "狀態": "正常" if task_queue.get("submission_contract_ready") else "檢查",
            "說明": _task_wiring_detail(task_queue),
        },
        {
            "項目": "Celery Worker",
            "狀態": _worker_label(task_queue),
            "說明": _worker_detail(task_queue),
        },
    ]


def task_queue_health_alert(service_snapshot: dict) -> dict | None:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    if not task_queue:
        return {
            "severity": "warning",
            "message": "尚未取得 task_queue 狀態；請確認 /services/status 是否可讀取。",
        }
    if not task_queue.get("ready"):
        return {
            "severity": "error",
            "message": f"背景任務 queue 尚不可送出：{_task_queue_submission_detail(task_queue)}",
        }
    if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
        return {
            "severity": "warning",
            "message": "Queue 可收任務，但 Celery worker 未回應；任務可能停在佇列。",
        }
    if task_queue.get("worker_online"):
        worker_count = int(task_queue.get("worker_count") or 0)
        return {
            "severity": "success",
            "message": f"Queue 與 Celery worker 可用；目前 {worker_count} 個 worker 節點回應。",
        }
    return {
        "severity": "info",
        "message": "Queue 可送出；worker ping 尚未執行或被跳過。",
    }


def task_queue_smoke_command(service_snapshot: dict) -> str | None:
    task_queue = _task_queue_from_snapshot(service_snapshot)
    commands = task_queue.get("smoke_commands")
    if isinstance(commands, list) and commands:
        return str(commands[0])
    return None


def external_deployment_warning_rows(upgrade_audit: dict) -> list[dict]:
    return [
        {
            "面向": _external_area_label(item),
            "能力": item.get("label") or item.get("capability") or "-",
            "狀態": item.get("status") or "-",
            "警示層級": _external_warning_level(item),
            "說明": _external_warning_detail(item),
            "診斷指令": "\n".join(_external_smoke_commands_from_payload(item)) or "-",
            "處理方向": item.get("remediation") or "-",
        }
        for item in _external_deployment_warning_items(upgrade_audit)
    ]


def external_deployment_smoke_commands(upgrade_audit: dict) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for item in _external_deployment_warning_items(upgrade_audit):
        for command in _external_smoke_commands_from_payload(item):
            if command in seen:
                continue
            seen.add(command)
            commands.append(command)
    return commands


def high_risk_filing_unlocker_rows(upgrade_audit: dict) -> list[dict]:
    item = _external_deployment_item_by_capability(
        upgrade_audit,
        "company_filing_high_risk_unlocker",
    )
    if not item:
        return []
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    provider_capability = (
        evidence.get("provider_capability")
        if isinstance(evidence.get("provider_capability"), dict)
        else {}
    )
    provider = str(evidence.get("configured_provider") or provider_capability.get("provider") or "-")
    provider_tier = str(evidence.get("provider_tier") or provider_capability.get("tier") or "-")
    recommended_env = _string_list(evidence.get("recommended_env"))
    compose_recommended_env = _string_list(evidence.get("compose_recommended_env"))
    env_lines = [*recommended_env]
    if compose_recommended_env:
        env_lines.extend(["# compose", *compose_recommended_env])
    domains = _string_list(evidence.get("domains"))
    smoke_cli = str(evidence.get("smoke_cli") or "").strip()
    next_action = item.get("remediation") or _high_risk_unlocker_next_action(evidence)
    return [
        {
            "項目": "Provider",
            "狀態": _ready_label(evidence.get("unlocker_provider_ready")),
            "目前": provider,
            "細節": (
                f"tier={provider_tier}；captcha_unlocker="
                f"{_yes_no(provider_capability.get('captcha_unlocker'))}"
            ),
            "下一步": next_action,
        },
        {
            "項目": "高風險防護",
            "狀態": _ready_label(evidence.get("captcha_challenge_ready")),
            "目前": _high_risk_unlocker_strategy(evidence),
            "細節": str(evidence.get("fallback_reason") or "-"),
            "下一步": _high_risk_unlocker_next_action(evidence),
        },
        {
            "項目": "高風險網域",
            "狀態": "範圍",
            "目前": "、".join(domains) if domains else "-",
            "細節": "MOPS / doc.twse / TWSE / TPEx",
            "下一步": "-",
        },
        {
            "項目": "建議 env",
            "狀態": "待設定" if env_lines and not evidence.get("unlocker_provider_ready") else "參考",
            "目前": "\n".join(env_lines) if env_lines else "-",
            "細節": "不改寫 .env；host-only 用 127.0.0.1，compose 服務內用 service DNS。",
            "下一步": "設定後重跑 high-risk filing unlocker smoke。",
        },
        {
            "項目": "MOPS smoke",
            "狀態": "可執行" if smoke_cli else "未提供",
            "目前": smoke_cli or "-",
            "細節": "驗證高風險公開文件入口的 render/unlocker contract。",
            "下一步": smoke_cli or "-",
        },
    ]


def local_unlocker_operation_rows(upgrade_audit: dict) -> list[dict]:
    item = _external_deployment_item_by_capability(
        upgrade_audit,
        "company_filing_high_risk_unlocker",
    )
    if not item:
        return []
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    return [
        {
            "項目": "一鍵啟動",
            "狀態": _local_unlocker_start_status(evidence),
            "指令": ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker",
            "說明": "啟動 Browserless 與 FlareSolverr，並在本次程序優先套用 unlocker provider。",
        },
        {
            "項目": "本機稽核",
            "狀態": "已就緒" if evidence.get("unlocker_provider_ready") else "待驗證",
            "指令": (
                ".venv/bin/python scripts/upgrade_audit.py "
                "--prefer-unlocker --wait-local-flaresolverr 20 "
                "--local-browser-render-defaults --json"
            ),
            "說明": "等待 FlareSolverr 8191 後套用本機 defaults；不改寫 .env。",
        },
        {
            "項目": "Fallback 判斷",
            "狀態": "目前路徑",
            "指令": "-",
            "說明": _local_unlocker_fallback_detail(evidence),
        },
        {
            "項目": "容器診斷",
            "狀態": "必要時",
            "指令": "docker compose ps flaresolverr && docker compose logs flaresolverr",
            "說明": "檢查 FlareSolverr container 是否啟動、port 是否綁定、image 是否拉取成功。",
        },
        {
            "項目": "MOPS smoke",
            "狀態": "可執行",
            "指令": _high_risk_mops_smoke_command(evidence),
            "說明": "驗證高風險公開資訊入口能走目前 render/unlocker contract 取得可解析 HTML。",
        },
    ]


def local_neo4j_operation_rows(upgrade_audit: dict) -> list[dict]:
    import_item = _external_deployment_item_by_capability(upgrade_audit, "neo4j_import")
    cypher_item = _external_deployment_item_by_capability(
        upgrade_audit,
        "graphrag_live_cypher_query",
    )
    if not (import_item or cypher_item):
        return []
    import_evidence = (
        import_item.get("evidence")
        if isinstance(import_item.get("evidence"), dict)
        else {}
    )
    cypher_evidence = (
        cypher_item.get("evidence")
        if isinstance(cypher_item.get("evidence"), dict)
        else {}
    )
    local_defaults = (
        import_evidence.get("local_docker_defaults")
        if isinstance(import_evidence.get("local_docker_defaults"), dict)
        else {}
    )
    neo4j_ready = bool(
        import_evidence.get("ready")
        or import_evidence.get("connection_ok")
        or cypher_evidence.get("neo4j_ready")
    )
    return [
        {
            "項目": "一鍵啟動",
            "狀態": "可重跑" if neo4j_ready else "待啟動",
            "指令": str(local_defaults.get("cli_start") or ".venv/bin/python scripts/start_system.py --start-dependencies"),
            "說明": "啟動本機 Neo4j，並在同一個 API/Streamlit 程序套用 docker-compose 預設連線值。",
        },
        {
            "項目": "本機稽核",
            "狀態": "已就緒" if neo4j_ready else "待驗證",
            "指令": ".venv/bin/python scripts/upgrade_audit.py --local-neo4j-defaults --wait-local-neo4j 20 --json",
            "說明": "等待 localhost:7687 後套用本機 Neo4j defaults；不改寫 .env。",
        },
        {
            "項目": "Payload dry-run",
            "狀態": "可執行" if import_evidence.get("payload_export_ready") else "檢查",
            "指令": _neo4j_payload_dry_run_command(import_evidence, cypher_evidence),
            "說明": _neo4j_payload_summary(import_evidence),
        },
        {
            "項目": "Live query smoke",
            "狀態": "可執行" if neo4j_ready else "需 Neo4j",
            "指令": _neo4j_live_smoke_command(import_evidence, cypher_evidence),
            "說明": "驗證 guarded read-only Cypher plan 與 Neo4j 查詢契約。",
        },
        {
            "項目": "Import-first smoke",
            "狀態": "可執行" if neo4j_ready else "需 Neo4j",
            "指令": _neo4j_import_first_smoke_command(import_evidence, cypher_evidence),
            "說明": "先匯入目前 GraphRAG payload，再執行 guarded live Cypher 查詢。",
        },
        {
            "項目": "容器診斷",
            "狀態": "必要時",
            "指令": "docker compose ps neo4j && docker compose logs neo4j",
            "說明": _local_neo4j_fallback_detail(import_evidence, cypher_evidence),
        },
    ]


def structured_filing_api_operation_rows(upgrade_audit: dict) -> list[dict]:
    item = _external_deployment_item_by_capability(
        upgrade_audit,
        "company_filing_structured_api_fallback",
    )
    if not item:
        return []
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else evidence
    provider_profile = (
        runtime.get("provider_profile")
        if isinstance(runtime.get("provider_profile"), dict)
        else {}
    )
    contract = (
        runtime.get("request_contract")
        if isinstance(runtime.get("request_contract"), dict)
        else evidence.get("request_contract")
        if isinstance(evidence.get("request_contract"), dict)
        else {}
    )
    return [
        {
            "項目": "Provider profile",
            "狀態": "已設定" if runtime.get("configured") else "待設定",
            "指令": _structured_filing_env_hint(runtime),
            "說明": _structured_filing_provider_detail(evidence, runtime, provider_profile),
        },
        {
            "項目": "Sample contract",
            "狀態": "可執行",
            "指令": _structured_filing_sample_command(runtime),
            "說明": "先用本機樣本 JSON 驗證 provider payload 是否可轉成 CompanyFilingDocument。",
        },
        {
            "項目": "Live smoke",
            "狀態": "可執行" if runtime.get("configured") else "待設定",
            "指令": _structured_filing_live_smoke_command(runtime),
            "說明": "設定 provider URL/token 後，驗證 live API、欄位轉換與公司/文件類型命中。",
        },
        {
            "項目": "Request contract",
            "狀態": str(contract.get("method") or "GET"),
            "指令": "-",
            "說明": _structured_filing_request_contract_detail(contract),
        },
        {
            "項目": "Required fields",
            "狀態": "必備",
            "指令": "-",
            "說明": _structured_filing_required_fields_detail(evidence, runtime),
        },
        {
            "項目": "Fallback 判斷",
            "狀態": "ready" if runtime.get("configured") else "not_configured",
            "指令": "-",
            "說明": _structured_filing_fallback_detail(runtime),
        },
    ]


def task_failure_drilldown_rows(task_summary: dict) -> list[dict]:
    failures = _task_summary_failures(task_summary)
    return [
        {
            "run_id": row.get("id") or "-",
            "operation": row.get("operation") or "-",
            "status": row.get("status") or "-",
            "task_id": row.get("task_id") or "-",
            "category": row.get("error_category") or "-",
            "severity": row.get("error_severity") or "-",
            "summary": row.get("error_summary") or "-",
            "retry": "可重試" if row.get("retryable") else "需人工",
            "retry_kind": row.get("retry_kind") or "-",
            "next_action": row.get("next_action") or _fallback_failure_next_action(row),
            "next_steps": _task_next_steps_text(row),
            "error": row.get("error") or "-",
            "started_at": row.get("started_at") or "-",
        }
        for row in failures
    ]


def task_retry_options(task_summary: dict) -> list[dict]:
    options = []
    for row in _task_summary_failures(task_summary):
        task_id = str(row.get("task_id") or "").strip()
        if not task_id or not row.get("retryable"):
            continue
        options.append(
            {
                "task_id": task_id,
                "label": _task_retry_option_label(row),
                "operation": row.get("operation") or "unknown",
                "run_id": row.get("id"),
                "retry_endpoint": row.get("retry_endpoint") or f"POST /tasks/{task_id}/retry",
            }
        )
    return options


def _task_summary_failures(task_summary: dict) -> list[dict]:
    if not isinstance(task_summary, dict):
        return []
    failures = task_summary.get("recent_failures")
    if not isinstance(failures, list):
        return []
    return [row for row in failures if isinstance(row, dict)]


def _task_retry_option_label(row: dict) -> str:
    task_id = str(row.get("task_id") or "")
    operation = str(row.get("operation") or "unknown")
    run_id = row.get("id") or "-"
    return f"{operation}｜run #{run_id}｜{task_id}"


def _fallback_failure_next_action(row: dict) -> str:
    if row.get("task_id"):
        return "查看任務狀態，確認 payload 是否支援自動重試。"
    return "缺少 task id；請從 run 明細檢查。"


def _task_next_steps_text(row: dict) -> str:
    next_steps = row.get("next_steps")
    if not isinstance(next_steps, list):
        return "-"
    steps = [str(step).strip() for step in next_steps if str(step).strip()]
    return "；".join(steps) if steps else "-"


def _task_queue_from_snapshot(service_snapshot: dict) -> dict:
    if not isinstance(service_snapshot, dict):
        return {}
    task_queue = service_snapshot.get("task_queue")
    return task_queue if isinstance(task_queue, dict) else {}


def _external_deployment_warning_items(upgrade_audit: dict) -> list[dict]:
    if not isinstance(upgrade_audit, dict):
        return []
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source_key in ("failures", "warnings", "optional_warnings", "all_warnings", "checks"):
        source_items = upgrade_audit.get(source_key)
        if not isinstance(source_items, list):
            continue
        for raw_item in source_items:
            if not isinstance(raw_item, dict):
                continue
            if not raw_item.get("external_integration"):
                continue
            if source_key == "checks" and raw_item.get("severity") == "pass":
                continue
            key = (str(raw_item.get("area") or ""), str(raw_item.get("capability") or ""))
            if key in seen:
                continue
            seen.add(key)
            item = dict(raw_item)
            item["_warning_source"] = source_key
            items.append(item)
    return items


def _external_deployment_item_by_capability(upgrade_audit: dict, capability: str) -> dict:
    if not isinstance(upgrade_audit, dict):
        return {}
    for source_key in ("failures", "warnings", "optional_warnings", "all_warnings", "checks"):
        source_items = upgrade_audit.get(source_key)
        if not isinstance(source_items, list):
            continue
        for raw_item in source_items:
            if not isinstance(raw_item, dict):
                continue
            if raw_item.get("capability") != capability:
                continue
            if not raw_item.get("external_integration"):
                continue
            item = dict(raw_item)
            item["_warning_source"] = source_key
            return item
    return {}


def _external_area_label(item: dict) -> str:
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    return area_labels.get(str(item.get("area") or ""), item.get("area") or "-")


def _external_warning_level(item: dict) -> str:
    if item.get("severity") == "fail":
        return "需處理"
    if item.get("optional") or item.get("_warning_source") == "optional_warnings":
        return "外部選配"
    return "注意"


def _external_warning_detail(item: dict) -> str:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    parts = [str(item.get("detail") or "").strip()]
    nested_detail = _first_external_detail_value(evidence)
    if nested_detail:
        parts.append(nested_detail)
    unique_parts: list[str] = []
    for part in parts:
        if not part or part in unique_parts:
            continue
        unique_parts.append(part)
    return "；".join(unique_parts) if unique_parts else "-"


def _first_external_detail_value(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in _EXTERNAL_DETAIL_KEYS and str(value or "").strip():
                return str(value).strip()
        for value in payload.values():
            detail = _first_external_detail_value(value)
            if detail:
                return detail
    if isinstance(payload, list):
        for value in payload:
            detail = _first_external_detail_value(value)
            if detail:
                return detail
    return None


def _external_smoke_commands_from_payload(payload: object) -> list[str]:
    commands: list[str] = []
    _collect_external_smoke_commands(payload, commands)
    deduped: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped


def _collect_external_smoke_commands(payload: object, commands: list[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            if (
                key_text in _EXTERNAL_SMOKE_COMMAND_KEYS
                or key_text.endswith("_smoke_cli")
                or key_text.endswith("_smoke_command")
            ):
                _append_external_command(value, commands)
            else:
                _collect_external_smoke_commands(value, commands)
    elif isinstance(payload, list):
        for value in payload:
            _collect_external_smoke_commands(value, commands)


def _append_external_command(value: object, commands: list[str]) -> None:
    if isinstance(value, str):
        command = value.strip()
        if command:
            commands.append(command)
        return
    if isinstance(value, list):
        for item in value:
            _append_external_command(item, commands)
        return
    if isinstance(value, dict):
        _collect_external_smoke_commands(value, commands)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _ready_label(value: object) -> str:
    return "Ready" if value else "待配置"


def _yes_no(value: object) -> str:
    return "是" if value else "否"


def _high_risk_unlocker_strategy(evidence: dict) -> str:
    parts = []
    if evidence.get("unlocker_provider_ready"):
        parts.append("unlocker provider ready")
    if evidence.get("ip_rotation_ready"):
        parts.append("proxy/IP rotation ready")
    if evidence.get("browser_only_render_ready"):
        parts.append("browser render fallback")
    return "；".join(parts) if parts else "尚未配置"


def _high_risk_unlocker_next_action(evidence: dict) -> str:
    if evidence.get("unlocker_provider_ready"):
        return "維持 unlocker provider，定期重跑 MOPS smoke。"
    if evidence.get("ip_rotation_ready"):
        return "已具備 IP rotation；仍建議補 FlareSolverr、ScrapingBee 或 BrightData。"
    if evidence.get("browser_only_render_ready"):
        return "目前只有 Browserless/Playwright；高風險 CAPTCHA 入口需補 unlocker provider。"
    return "設定 FlareSolverr、ScrapingBee 或 BrightData，或至少配置 rotating proxy。"


def _local_unlocker_start_status(evidence: dict) -> str:
    if evidence.get("unlocker_provider_ready"):
        return "可重跑"
    if evidence.get("browser_only_render_ready") or evidence.get("ip_rotation_ready"):
        return "建議升級"
    return "待啟動"


def _local_unlocker_fallback_detail(evidence: dict) -> str:
    if evidence.get("unlocker_provider_ready"):
        return "目前使用 FlareSolverr、ScrapingBee 或 BrightData 等 unlocker provider。"
    if evidence.get("ip_rotation_ready"):
        return "目前具備 proxy/IP rotation，但高風險 CAPTCHA 入口仍缺 unlocker provider。"
    if evidence.get("browser_only_render_ready"):
        return "目前會 fallback 到 Browserless/Playwright；高風險 CAPTCHA 入口仍需 unlocker。"
    return "尚未配置 browser render、proxy 或 unlocker；高風險公開文件容易只取到阻擋頁。"


def _high_risk_mops_smoke_command(evidence: dict) -> str:
    smoke_cli = str(evidence.get("smoke_cli") or "").strip()
    if smoke_cli:
        return smoke_cli
    return ".venv/bin/python scripts/company_filing_render_smoke.py --url https://mops.twse.com.tw/ --json"


def _neo4j_payload_dry_run_command(import_evidence: dict, cypher_evidence: dict) -> str:
    return str(
        import_evidence.get("payload_dry_run_cli")
        or cypher_evidence.get("payload_dry_run_cli")
        or ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run"
    )


def _neo4j_live_smoke_command(import_evidence: dict, cypher_evidence: dict) -> str:
    return str(
        cypher_evidence.get("smoke_cli")
        or import_evidence.get("smoke_cli")
        or ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
    )


def _neo4j_import_first_smoke_command(import_evidence: dict, cypher_evidence: dict) -> str:
    return str(
        import_evidence.get("import_smoke_cli")
        or cypher_evidence.get("import_smoke_cli")
        or ".venv/bin/python scripts/neo4j_graphrag_smoke.py --tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json"
    )


def _neo4j_payload_summary(import_evidence: dict) -> str:
    if not import_evidence.get("payload_export_ready"):
        return "GraphRAG payload 尚未可匯出；請先檢查 /supply-chain/graph/neo4j。"
    node_count = int(import_evidence.get("payload_node_count") or 0)
    structural_edges = int(import_evidence.get("payload_structural_edge_count") or 0)
    peer_edges = int(import_evidence.get("payload_peer_edge_count") or 0)
    statements = int(import_evidence.get("payload_statement_count") or 0)
    return f"payload ready：nodes={node_count}、structural_edges={structural_edges}、peer_edges={peer_edges}、statements={statements}。"


def _local_neo4j_fallback_detail(import_evidence: dict, cypher_evidence: dict) -> str:
    if import_evidence.get("ready") or import_evidence.get("connection_ok") or cypher_evidence.get("neo4j_ready"):
        database = import_evidence.get("database") or "neo4j"
        return f"Neo4j live query/import 已就緒；database={database}。"
    reason = (
        import_evidence.get("fallback_reason")
        or import_evidence.get("connection_error")
        or cypher_evidence.get("fallback_reason")
        or "missing_settings:neo4j_uri"
    )
    return f"目前只使用本機 GraphRAG plan/payload；live Neo4j 尚未就緒：{reason}。"


def _structured_filing_env_hint(runtime: dict) -> str:
    provider = str(runtime.get("provider") or runtime.get("provider_profile_key") or "tej")
    return "\n".join(
        [
            f"COMPANY_FILING_STRUCTURED_API_PROVIDER={provider}",
            "COMPANY_FILING_STRUCTURED_API_URL=<provider-json-endpoint>",
            "COMPANY_FILING_STRUCTURED_API_TOKEN=<token>",
        ]
    )


def _structured_filing_provider_detail(
    evidence: dict,
    runtime: dict,
    provider_profile: dict,
) -> str:
    provider = runtime.get("provider") or provider_profile.get("provider") or "-"
    profile = runtime.get("provider_profile_key") or provider_profile.get("profile_key") or "-"
    supported = _string_list(evidence.get("supported_provider_examples")) or _string_list(
        runtime.get("supported_provider_examples")
    )
    supported_text = "、".join(supported) if supported else "-"
    return f"provider={provider}；profile={profile}；supported={supported_text}。"


def _structured_filing_sample_command(runtime: dict) -> str:
    return str(
        runtime.get("sample_contract_cli")
        or ".venv/bin/python scripts/structured_company_filing_smoke.py --sample-json examples/structured_company_filing_sample.json --ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    )


def _structured_filing_live_smoke_command(runtime: dict) -> str:
    return str(
        runtime.get("smoke_cli")
        or ".venv/bin/python scripts/structured_company_filing_smoke.py --ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
    )


def _structured_filing_request_contract_detail(contract: dict) -> str:
    query_keys = _string_list(contract.get("query_param_keys"))
    rows = _string_list(contract.get("response_rows"))
    auth = str(contract.get("auth_mode") or "-")
    document_param = str(contract.get("document_type_param") or "-")
    return (
        f"auth={auth}；document_type_param={document_param}；"
        f"query={','.join(query_keys) or '-'}；rows={','.join(rows) or '-'}。"
    )


def _structured_filing_required_fields_detail(evidence: dict, runtime: dict) -> str:
    fields = _string_list(runtime.get("required_document_fields")) or _string_list(
        evidence.get("required_document_fields")
    )
    aliases = _string_list(runtime.get("response_row_aliases")) or _string_list(
        evidence.get("response_row_aliases")
    )
    return (
        "fields="
        + ("；".join(fields) if fields else "-")
        + "；response_rows="
        + ("、".join(aliases) if aliases else "-")
        + "。"
    )


def _structured_filing_fallback_detail(runtime: dict) -> str:
    if runtime.get("configured"):
        provider = runtime.get("provider") or runtime.get("provider_profile_key") or "-"
        return f"structured filing API 已設定；provider={provider}。"
    reason = runtime.get("fallback_reason") or "missing_structured_api_provider_or_url"
    return f"尚未設定授權資料源；目前會改用 Google News/官方網站搜尋與既有爬蟲流程：{reason}。"


def _ok_label(value: object) -> str:
    return "正常" if value else "檢查"


def _task_queue_submission_detail(task_queue: dict) -> str:
    if task_queue.get("ready"):
        if task_queue.get("worker_ping_checked") and not task_queue.get("worker_online"):
            return "Redis 與 task wiring 可送出；worker 未回應時任務會先留在 queue。"
        return "Redis broker/backend 與 Celery task wiring 已可提交。"
    issues = []
    if not task_queue:
        issues.append("尚未取得 task_queue 診斷")
    if not task_queue.get("broker_configured"):
        issues.append("Redis broker URL 未設定")
    if not task_queue.get("broker_ok"):
        issues.append("Redis broker 未連線")
    if not task_queue.get("backend_ok"):
        issues.append("Redis backend 未連線")
    if not task_queue.get("submission_contract_ready"):
        issues.append("Celery task exports 或 task name 尚未對齊")
    return "；".join(issues) or "狀態未知"


def _connection_detail(task_queue: dict, url_key: str) -> str:
    url = task_queue.get(url_key) or "-"
    redis_error = task_queue.get("redis_error")
    if redis_error:
        return f"{url}；Redis error: {redis_error}"
    return str(url)


def _task_wiring_detail(task_queue: dict) -> str:
    if task_queue.get("submission_contract_ready"):
        return "必要 Celery task exports 與 task name 已對齊。"
    missing = task_queue.get("missing_task_exports")
    if isinstance(missing, list) and missing:
        return "缺少 exports：" + "、".join(str(item) for item in missing)
    if task_queue.get("task_export_error"):
        return f"task export error: {task_queue['task_export_error']}"
    if task_queue.get("task_names_match_expected") is False:
        return "task name 與預期不一致。"
    return "尚未取得 task wiring 診斷。"


def _worker_label(task_queue: dict) -> str:
    if not task_queue.get("worker_ping_checked"):
        return "未檢查"
    if task_queue.get("worker_online"):
        return "在線"
    return "未回應"


def _worker_detail(task_queue: dict) -> str:
    if task_queue.get("worker_online"):
        nodes = task_queue.get("worker_nodes") or []
        if nodes:
            return "回應節點：" + "、".join(str(node) for node in nodes)
        return f"worker_count={int(task_queue.get('worker_count') or 0)}"
    if not task_queue.get("worker_ping_checked"):
        reason = task_queue.get("worker_ping_skipped_reason") or "worker ping 未執行"
        return f"未執行 ping：{reason}"
    details = ["worker ping 無回應"]
    if task_queue.get("worker_ping_error"):
        details.append(f"錯誤：{task_queue['worker_ping_error']}")
    timeout = task_queue.get("worker_ping_timeout_seconds")
    if timeout:
        details.append(f"timeout {timeout}s")
    return "；".join(details)


def upgrade_audit_html(audit: dict) -> str:
    summary = audit.get("summary") or {}
    status = str(audit.get("overall_status") or "unknown")
    implementation = audit.get("implementation") or {}
    deployment = audit.get("deployment") or {}
    implementation_status = str(
        implementation.get("status") or summary.get("implementation_status") or "unknown"
    )
    deployment_status = str(deployment.get("status") or summary.get("deployment_status") or "unknown")
    status_labels = {
        "ready": "通過",
        "caution": "注意",
        "failed": "需處理",
        "unknown": "未評估",
    }
    strict_label = "正式部署" if audit.get("strict_external") else "一般檢查"
    total = int(summary.get("total_checks") or 0)
    ready = int(summary.get("ready") or 0)
    warnings = int(summary.get("warnings") or 0)
    optional_warnings = int(summary.get("optional_warnings") or 0)
    failures = int(summary.get("failures") or 0)
    implementation_ready = int(implementation.get("ready") or 0)
    implementation_total = int(implementation.get("total_checks") or 0)
    deployment_ready = int(deployment.get("ready") or 0)
    deployment_total = int(deployment.get("total_checks") or 0)
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    area_cards = []
    for area_key, area in sorted((audit.get("areas") or {}).items()):
        area_cards.append(
            '<div class="upgrade-audit-area"><strong>{label}</strong>'
            "<span>通過 {ready} / 注意 {warnings} / 需處理 {failures}</span></div>".format(
                label=escape(area_labels.get(area_key, str(area_key))),
                ready=int(area.get("ready") or 0),
                warnings=int(area.get("warnings") or 0),
                failures=int(area.get("failures") or 0),
            )
        )
    return """
    <div class="result-shell">
        <div class="section-title">升級稽核</div>
        <div class="upgrade-audit-grid">
            <div class="upgrade-audit-tile">
                <span>核心升級</span>
                <strong><span class="upgrade-audit-status {implementation_status_class}">{implementation_status_label}</span></strong>
            </div>
            <div class="upgrade-audit-tile">
                <span>外部整合</span>
                <strong><span class="upgrade-audit-status {deployment_status_class}">{deployment_status_label}</span></strong>
            </div>
            <div class="upgrade-audit-tile"><span>檢查模式</span><strong>{strict_label}</strong></div>
            <div class="upgrade-audit-tile"><span>通過項目</span><strong>{ready}/{total}</strong></div>
        </div>
        <div class="upgrade-audit-note">
            整體狀態：{status_label}；核心 {implementation_ready}/{implementation_total} 通過，外部 {deployment_ready}/{deployment_total} 通過；注意 {warnings} 項、外部選配 {optional_warnings} 項、需處理 {failures} 項。
        </div>
        <div class="upgrade-audit-areas">{areas}</div>
    </div>
    """.format(
        status_label=escape(status_labels.get(status, status)),
        implementation_status_class=escape(
            implementation_status if implementation_status in {"ready", "caution", "failed"} else "unknown"
        ),
        implementation_status_label=escape(status_labels.get(implementation_status, implementation_status)),
        deployment_status_class=escape(
            deployment_status if deployment_status in {"ready", "caution", "failed"} else "unknown"
        ),
        deployment_status_label=escape(status_labels.get(deployment_status, deployment_status)),
        strict_label=escape(strict_label),
        ready=ready,
        total=total,
        implementation_ready=implementation_ready,
        implementation_total=implementation_total,
        deployment_ready=deployment_ready,
        deployment_total=deployment_total,
        warnings=warnings,
        optional_warnings=optional_warnings,
        failures=failures,
        areas="".join(area_cards) or "<div class='upgrade-audit-area'><strong>未評估</strong><span>尚無稽核資料</span></div>",
    )


def upgrade_audit_rows(audit: dict) -> list[dict]:
    severity_labels = {"pass": "通過", "warn": "注意", "fail": "需處理"}
    area_labels = {
        "ai_rag": "AI / RAG",
        "architecture": "系統架構",
        "data_business_logic": "資料與業務邏輯",
    }
    return [
        {
            "面向": area_labels.get(str(check.get("area")), check.get("area")),
            "能力": check.get("label") or check.get("capability"),
            "結果": severity_labels.get(str(check.get("severity")), check.get("severity")),
            "目前狀態": check.get("status"),
            "說明": check.get("detail") or "-",
            "處理方向": check.get("remediation") or "-",
        }
        for check in audit.get("checks") or []
    ]
