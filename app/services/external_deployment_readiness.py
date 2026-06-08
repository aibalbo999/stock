from __future__ import annotations

EXTERNAL_SMOKE_COMMAND_KEYS = frozenset(
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
EXTERNAL_DETAIL_KEYS = frozenset(
    {
        "fallback_reason",
        "connection_error",
        "runtime_error",
        "error",
        "reason",
    }
)
EXTERNAL_READINESS_METADATA = {
    ("ai_rag", "neo4j_import"): {
        "priority": "P1",
        "impact": "GraphRAG payload 匯入與 live graph context。",
    },
    ("ai_rag", "graphrag_live_cypher_query"): {
        "priority": "P1",
        "impact": "LLM guarded Cypher、shortest-path 與上下游衝擊推理。",
    },
    ("ai_rag", "visual_rag"): {
        "priority": "P2",
        "impact": "掃描型 PDF、圖表與複雜財報頁面解析。",
    },
    ("data_business_logic", "company_filing_pdf_table_parser_runtime"): {
        "priority": "P2",
        "impact": "PDF 財報與法說會表格抽取品質。",
    },
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): {
        "priority": "P1",
        "impact": "動態頁、被擋頁與一般公司文件 render fallback。",
    },
    ("data_business_logic", "company_filing_high_risk_unlocker"): {
        "priority": "P0",
        "impact": "MOPS、doc.twse、TWSE/TPEx 高風險文件入口。",
    },
    ("data_business_logic", "company_filing_structured_api_fallback"): {
        "priority": "P1",
        "impact": "法說會簡報、重大訊息與專業財經資料備援。",
    },
}
EXTERNAL_LOCAL_ACTION_METADATA = {
    ("ai_rag", "neo4j_import"): {
        "wait_key": "neo4j",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-neo4j-defaults --wait-local-neo4j 20 --json"
        ),
    },
    ("ai_rag", "graphrag_live_cypher_query"): {
        "wait_key": "neo4j",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--local-neo4j-defaults --wait-local-neo4j 20 --json"
        ),
    },
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): {
        "wait_key": "browserless",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--wait-local-browserless 20 --local-browser-render-defaults --json"
        ),
    },
    ("data_business_logic", "company_filing_high_risk_unlocker"): {
        "wait_key": "flaresolverr",
        "start_command": ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker",
        "verify_command": (
            ".venv/bin/python scripts/upgrade_audit.py "
            "--prefer-unlocker --wait-local-flaresolverr 20 "
            "--local-browser-render-defaults --json"
        ),
    },
}


def external_deployment_readiness_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for item in external_deployment_readiness_items(upgrade_audit):
        metadata = external_deployment_readiness_metadata(item)
        local_action = external_deployment_local_action(
            item,
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
        rows.append(
            {
                "優先級": metadata["priority"],
                "項目": item.get("label") or item.get("capability") or "-",
                "狀態": external_deployment_readiness_state(item),
                "部署決策": external_deployment_readiness_decision(item),
                "本機動作": local_action["state"],
                "本機指令": local_action["command"],
                "影響範圍": metadata["impact"],
                "下一步": item.get("remediation") or "-",
                "驗證指令": external_deployment_command_summary(
                    external_smoke_commands_from_payload(item)
                ),
            }
        )
    return rows


def external_deployment_readiness_items(upgrade_audit: dict) -> list[dict]:
    if not isinstance(upgrade_audit, dict):
        return []
    items_with_index: list[tuple[int, dict]] = []
    seen: set[tuple[str, str]] = set()
    index = 0
    for source_key in ("checks", "failures", "warnings", "optional_warnings", "all_warnings"):
        source_items = upgrade_audit.get(source_key)
        if not isinstance(source_items, list):
            continue
        for raw_item in source_items:
            if not isinstance(raw_item, dict) or not _is_external_readiness_item(raw_item):
                continue
            key = (str(raw_item.get("area") or ""), str(raw_item.get("capability") or ""))
            if key in seen:
                continue
            seen.add(key)
            item = dict(raw_item)
            item["_warning_source"] = source_key
            items_with_index.append((index, item))
            index += 1
    return [
        item
        for _, item in sorted(
            items_with_index,
            key=lambda indexed_item: _external_readiness_sort_key(indexed_item[1], indexed_item[0]),
        )
    ]


def external_deployment_readiness_metadata(item: dict) -> dict:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    metadata = EXTERNAL_READINESS_METADATA.get(key, {})
    return {
        "priority": str(metadata.get("priority") or "P2"),
        "impact": str(metadata.get("impact") or item.get("detail") or "-"),
    }


def external_deployment_local_action(
    item: dict,
    upgrade_audit: dict,
    *,
    local_dependency_status: dict | None = None,
) -> dict:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    metadata = EXTERNAL_LOCAL_ACTION_METADATA.get(key)
    if not metadata:
        return {
            "state": "已就緒" if item.get("severity") == "pass" else "需外部設定",
            "command": "-",
        }
    wait_status = (
        upgrade_audit.get("local_dependency_wait") if isinstance(upgrade_audit, dict) else {}
    )
    wait_status = wait_status if isinstance(wait_status, dict) else {}
    wait_key = str(metadata.get("wait_key") or "")
    verify_command = str(metadata.get("verify_command") or "-")
    if wait_key and wait_key in wait_status:
        return {
            "state": "已啟動" if wait_status.get(wait_key) is True else "驗證失敗",
            "command": verify_command,
        }
    port_state = _local_dependency_port_state(local_dependency_status, wait_key)
    if port_state is True:
        return {"state": "已啟動", "command": verify_command}
    if _external_readiness_item_ready(item):
        return {"state": "已啟動", "command": verify_command}
    return {
        "state": "可啟動",
        "command": str(metadata.get("start_command") or verify_command or "-"),
    }


def local_dependency_status_rows(service_snapshot: dict) -> list[dict]:
    status = (
        service_snapshot.get("local_dependencies")
        if isinstance(service_snapshot.get("local_dependencies"), dict)
        else {}
    )
    ports = status.get("ports") if isinstance(status.get("ports"), list) else []
    return [
        {
            "服務": row.get("label") or row.get("service") or "-",
            "狀態": "已啟動" if row.get("open") else "未偵測",
            "本機端口": f"{row.get('host') or '127.0.0.1'}:{row.get('port') or '-'}",
            "用途": row.get("role") or "-",
        }
        for row in ports
        if isinstance(row, dict)
    ]


def local_dependency_repair_rows(service_snapshot: dict) -> list[dict]:
    status = (
        service_snapshot.get("local_dependencies")
        if isinstance(service_snapshot.get("local_dependencies"), dict)
        else {}
    )
    repair_plan = status.get("repair_plan") if isinstance(status.get("repair_plan"), list) else []
    return [
        {
            "項目": row.get("item") or row.get("項目") or "-",
            "狀態": row.get("state") or row.get("狀態") or "-",
            "下一步": row.get("next_step") or row.get("下一步") or "-",
            "修復指令": row.get("repair_command") or row.get("修復指令") or "-",
            "驗證指令": row.get("verify_command") or row.get("驗證指令") or "-",
        }
        for row in repair_plan
        if isinstance(row, dict)
    ]


def local_dependency_last_start_rows(service_snapshot: dict) -> list[dict]:
    status = (
        service_snapshot.get("local_dependencies")
        if isinstance(service_snapshot.get("local_dependencies"), dict)
        else {}
    )
    last_start = status.get("last_start") if isinstance(status.get("last_start"), dict) else {}
    if not last_start.get("available"):
        return []
    updated_at = str(last_start.get("updated_at") or "-")
    rows = [
        {
            "項目": "最近啟動",
            "狀態": last_start.get("status") or "-",
            "更新時間": updated_at,
            "說明": last_start.get("message") or "-",
            "細節": _local_dependency_last_start_detail(last_start),
        }
    ]
    wait_status = last_start.get("wait") if isinstance(last_start.get("wait"), dict) else {}
    for service, ready in sorted(wait_status.items()):
        if isinstance(ready, bool):
            rows.append(
                {
                    "項目": f"等待 {_local_dependency_wait_label(str(service))}",
                    "狀態": "就緒" if ready else "尚未就緒",
                    "更新時間": updated_at,
                    "說明": "scripts/start_system.py --start-dependencies 等待結果",
                    "細節": str(last_start.get("path") or "-"),
                }
            )
        elif isinstance(ready, dict):
            rows.append(
                {
                    "項目": _local_dependency_wait_label(str(service)),
                    "狀態": ready.get("status") or "-",
                    "更新時間": updated_at,
                    "說明": ready.get("reason") or "-",
                    "細節": ready.get("provider") or ready.get("browser") or "-",
                }
            )
    return rows


def _local_dependency_last_start_detail(last_start: dict) -> str:
    services = "、".join(str(service) for service in last_start.get("services") or []) or "-"
    env_keys = "、".join(str(key) for key in last_start.get("applied_env_keys") or []) or "-"
    unlocker = "含 unlocker" if last_start.get("include_unlocker") else "核心依賴"
    wait_seconds = last_start.get("wait_seconds")
    wait_text = f"等待 {wait_seconds}s" if wait_seconds is not None else "等待時間未記錄"
    return f"{unlocker}；服務 {services}；{wait_text}；env keys {env_keys}"


def _local_dependency_wait_label(service: str) -> str:
    labels = {
        "neo4j": "Neo4j 7687",
        "browserless": "Browserless 3000",
        "chroma": "Chroma 8001",
        "postgres": "Postgres 5432",
        "redis": "Redis 6379",
        "flaresolverr": "FlareSolverr 8191",
        "browser_render_fallback": "Browser render fallback",
    }
    return labels.get(service, service)


def external_deployment_readiness_state(item: dict) -> str:
    severity = str(item.get("severity") or "")
    if severity == "pass":
        return "Ready"
    if severity == "fail":
        return "阻塞"
    if item.get("optional") or item.get("_warning_source") == "optional_warnings":
        return "外部選配"
    if severity == "warn":
        return "待配置"
    return str(item.get("status") or "-")


def external_deployment_readiness_decision(item: dict) -> str:
    severity = str(item.get("severity") or "")
    if severity == "pass":
        return "已就緒"
    if severity == "fail":
        return "正式部署前必修"
    if item.get("optional") or item.get("_warning_source") == "optional_warnings":
        return "需要該能力時配置"
    if severity == "warn":
        return "建議優先處理"
    return "檢查"


def external_deployment_command_summary(commands: list[str]) -> str:
    if not commands:
        return "-"
    if len(commands) == 1:
        return commands[0]
    return f"{commands[0]}\n另有 {len(commands) - 1} 個 smoke 指令，見下方單項診斷指令。"


def external_deployment_warning_rows(upgrade_audit: dict) -> list[dict]:
    return [
        {
            "面向": _external_area_label(item),
            "能力": item.get("label") or item.get("capability") or "-",
            "狀態": item.get("status") or "-",
            "警示層級": _external_warning_level(item),
            "說明": _external_warning_detail(item),
            "診斷指令": "\n".join(external_smoke_commands_from_payload(item)) or "-",
            "處理方向": item.get("remediation") or "-",
        }
        for item in external_deployment_warning_items(upgrade_audit)
    ]


def external_deployment_smoke_commands(upgrade_audit: dict) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for item in external_deployment_warning_items(upgrade_audit):
        for command in external_smoke_commands_from_payload(item):
            if command in seen:
                continue
            seen.add(command)
            commands.append(command)
    return commands


def external_deployment_warning_items(upgrade_audit: dict) -> list[dict]:
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


def external_deployment_item_by_capability(upgrade_audit: dict, capability: str) -> dict:
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


def _is_external_readiness_item(item: dict) -> bool:
    if not item.get("external_integration"):
        return False
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    return bool(item.get("deployment_check") or key in EXTERNAL_READINESS_METADATA)


def _external_readiness_item_ready(item: dict) -> bool:
    if item.get("severity") == "pass" or item.get("status") == "ready":
        return True
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    if key == ("data_business_logic", "company_filing_high_risk_unlocker"):
        return bool(
            evidence.get("high_risk_mitigation_ready")
            or evidence.get("unlocker_provider_ready")
            or evidence.get("captcha_challenge_ready")
        )
    if key == ("data_business_logic", "company_filing_browser_or_proxy_fallback"):
        return bool(
            evidence.get("ready")
            or evidence.get("browser_or_proxy_fallback_configured")
            or evidence.get("browser_render_configured")
            or evidence.get("playwright_render_configured")
        )
    return bool(
        evidence.get("ready")
        or evidence.get("connection_ok")
        or evidence.get("neo4j_ready")
        or evidence.get("unlocker_provider_ready")
        or evidence.get("captcha_challenge_ready")
        or evidence.get("browser_or_proxy_fallback_configured")
        or evidence.get("playwright_render_configured")
    )


def external_deployment_item_ready(item: dict) -> bool:
    return _external_readiness_item_ready(item)


def _local_dependency_port_state(local_dependency_status: dict | None, service: str) -> bool | None:
    if not service or not isinstance(local_dependency_status, dict):
        return None
    ports = local_dependency_status.get("ports")
    if not isinstance(ports, list):
        return None
    for row in ports:
        if isinstance(row, dict) and row.get("service") == service:
            return bool(row.get("open"))
    return None


def _external_readiness_sort_key(item: dict, index: int) -> tuple[int, int, int]:
    severity_order = {"fail": 0, "warn": 1, "pass": 2}
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    metadata = external_deployment_readiness_metadata(item)
    return (
        severity_order.get(str(item.get("severity") or ""), 3),
        priority_order.get(metadata["priority"], 4),
        index,
    )


def external_smoke_commands_from_payload(payload: object) -> list[str]:
    commands: list[str] = []
    collect_external_smoke_commands(payload, commands)
    deduped: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped


def collect_external_smoke_commands(payload: object, commands: list[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            if (
                key_text in EXTERNAL_SMOKE_COMMAND_KEYS
                or key_text.endswith("_smoke_cli")
                or key_text.endswith("_smoke_command")
            ):
                append_external_command(value, commands)
            else:
                collect_external_smoke_commands(value, commands)
    elif isinstance(payload, list):
        for value in payload:
            collect_external_smoke_commands(value, commands)


def append_external_command(value: object, commands: list[str]) -> None:
    if isinstance(value, str):
        command = value.strip()
        if command:
            commands.append(command)
        return
    if isinstance(value, list):
        for item in value:
            append_external_command(item, commands)
        return
    if isinstance(value, dict):
        collect_external_smoke_commands(value, commands)


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def ready_label(value: object) -> str:
    return "Ready" if value else "待配置"


def yes_no(value: object) -> str:
    return "是" if value else "否"


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
            if key in EXTERNAL_DETAIL_KEYS and str(value or "").strip():
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
