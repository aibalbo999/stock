from __future__ import annotations

from typing import Any


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
EXTERNAL_ENV_KEY_HINTS = {
    "NEO4J_URI": {
        "default": "neo4j://localhost:7687",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "NEO4J_USER": {
        "default": "neo4j",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "NEO4J_PASSWORD": {
        "default": "<password>",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "NEO4J_DATABASE": {
        "default": "neo4j",
        "scope": "GraphRAG live import / guarded Cypher query",
    },
    "COMPANY_FILING_BROWSER_RENDER_ENABLED": {
        "default": "true",
        "scope": "公司文件 browser render / unlocker",
    },
    "COMPANY_FILING_BROWSER_RENDER_PROVIDER": {
        "default": "flaresolverr",
        "scope": "公司文件 browser render / unlocker",
    },
    "COMPANY_FILING_BROWSER_RENDER_URL": {
        "default": "http://127.0.0.1:8191/v1",
        "scope": "公司文件 browser render / unlocker",
    },
    "COMPANY_FILING_BROWSER_RENDER_TOKEN": {
        "default": "<token>",
        "scope": "ScrapingBee / BrightData managed unlocker",
    },
    "COMPANY_FILING_PROXY_URLS": {
        "default": "<rotating-proxy-list>",
        "scope": "高風險公開文件 IP rotation",
    },
    "COMPANY_FILING_STRUCTURED_API_PROVIDER": {
        "default": "tej",
        "scope": "公司文件結構化 API 備援",
    },
    "COMPANY_FILING_STRUCTURED_API_URL": {
        "default": "<provider-json-endpoint>",
        "scope": "公司文件結構化 API 備援",
    },
    "COMPANY_FILING_STRUCTURED_API_TOKEN": {
        "default": "<token>",
        "scope": "TEJ / 專業財經資料 API",
    },
    "COMPANY_FILING_VISUAL_RAG_ENABLED": {
        "default": "true",
        "scope": "PDF 圖表與複雜表格 VLM fallback",
    },
    "COMPANY_FILING_VISUAL_RAG_MODEL": {
        "default": "gemini-3.5-flash",
        "scope": "PDF 圖表與複雜表格 VLM fallback",
    },
    "GOOGLE_API_KEY": {
        "default": "<token>",
        "scope": "Gemini / Visual RAG / LLM fallback",
    },
    "GOOGLE_API_KEYS": {
        "default": "<token1>,<token2>",
        "scope": "Gemini / Visual RAG / LLM fallback",
    },
}
EXTERNAL_CAPABILITY_ENV_DEFAULTS = {
    ("ai_rag", "neo4j_import"): (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
    ),
    ("ai_rag", "graphrag_live_cypher_query"): (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
    ),
    ("ai_rag", "visual_rag"): (
        "COMPANY_FILING_VISUAL_RAG_ENABLED",
        "COMPANY_FILING_VISUAL_RAG_MODEL",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEYS",
    ),
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): (
        "COMPANY_FILING_BROWSER_RENDER_ENABLED",
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_PROXY_URLS",
    ),
    ("data_business_logic", "company_filing_high_risk_unlocker"): (
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
        "COMPANY_FILING_BROWSER_RENDER_TOKEN",
        "COMPANY_FILING_PROXY_URLS",
    ),
    ("data_business_logic", "company_filing_structured_api_fallback"): (
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
        "COMPANY_FILING_STRUCTURED_API_TOKEN",
    ),
}


def external_deployment_env_gap_report(
    *,
    upgrade_audit: dict[str, Any] | None = None,
    service_snapshot: dict[str, Any] | None = None,
    strict_external: bool = False,
) -> dict[str, Any]:
    from app.services.service_status import service_status
    from app.services.upgrade_audit import audit_upgrade_capabilities

    audit = (
        audit_upgrade_capabilities(strict_external=strict_external)
        if upgrade_audit is None
        else upgrade_audit
    )
    snapshot = service_status() if service_snapshot is None else service_snapshot
    rows = external_deployment_env_key_rows(audit, snapshot)
    missing_count = sum(1 for row in rows if row.get("狀態") == "缺少")
    recommended_count = sum(1 for row in rows if row.get("狀態") == "建議")
    manual_secret_count = sum(1 for row in rows if row.get("處理類型") == "需人工密鑰")
    local_action_count = sum(1 for row in rows if row.get("處理類型") == "本機可套用")
    return {
        "status": "action_required" if rows else "ready",
        "gap_count": len(rows),
        "missing_count": missing_count,
        "recommended_count": recommended_count,
        "manual_secret_count": manual_secret_count,
        "local_action_count": local_action_count,
        "rows": rows,
        "local_start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "local_unlocker_start_command": (
            ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker"
        ),
        "strict_external": bool(strict_external),
    }


def format_external_deployment_env_gap_report(report: dict[str, Any]) -> str:
    lines = [
        (
            f"External deployment env gaps: {report['status']} "
            f"({report['gap_count']} gaps; missing={report['missing_count']}; "
            f"recommended={report['recommended_count']})"
        )
    ]
    if not report.get("rows"):
        lines.append("No external deployment env gaps detected.")
        return "\n".join(lines)
    for row in report["rows"]:
        lines.append(
            f"- [{row['狀態']}] {row['優先級']} {row['能力']} :: "
            f"{row['設定鍵']} ({row['處理類型']})"
        )
        lines.append(f"  value: {row['建議值']}")
        lines.append(f"  action: {row['維護動作']}")
        lines.append(f"  verify: {row['驗證指令']}")
    return "\n".join(lines)


def external_deployment_env_key_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for item in [
        *external_deployment_readiness_items(upgrade_audit),
        *_service_snapshot_external_env_items(service_snapshot or {}),
    ]:
        if external_deployment_item_ready(item):
            continue
        metadata = external_deployment_readiness_metadata(item)
        env_summary = _external_env_summary(item)
        verify_command = external_deployment_command_summary(
            external_smoke_commands_from_payload(item)
        )
        capability = str(item.get("capability") or "")
        source = str(item.get("_env_source") or "upgrade audit")
        for env_key, status in _external_env_key_actions(item, env_summary):
            key = (capability, env_key, status)
            if key in seen:
                continue
            seen.add(key)
            hint = EXTERNAL_ENV_KEY_HINTS.get(env_key, {})
            recommended_value = (
                env_summary["recommended"].get(env_key) or hint.get("default") or "-"
            )
            resolution_type = _external_env_resolution_type(env_key, recommended_value)
            rows.append(
                {
                    "優先級": metadata["priority"],
                    "能力": item.get("label") or item.get("capability") or "-",
                    "設定鍵": env_key,
                    "狀態": status,
                    "目前": "未設定" if status == "缺少" else "建議確認",
                    "建議值": recommended_value,
                    "用途": hint.get("scope") or metadata["impact"],
                    "來源": source,
                    "處理類型": resolution_type,
                    "維護動作": _external_env_maintenance_action(
                        item,
                        env_key,
                        recommended_value,
                        resolution_type,
                    ),
                    "下一步": _external_env_key_next_step(item, env_key, status),
                    "驗證指令": verify_command,
                }
            )
    return sorted(rows, key=_external_env_key_row_sort_key)


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
            key=lambda indexed_item: _external_readiness_sort_key(
                indexed_item[1],
                indexed_item[0],
            ),
        )
    ]


def external_deployment_readiness_metadata(item: dict) -> dict:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    metadata = EXTERNAL_READINESS_METADATA.get(key, {})
    return {
        "priority": str(metadata.get("priority") or "P2"),
        "impact": str(metadata.get("impact") or item.get("detail") or "-"),
    }


def external_deployment_item_ready(item: dict) -> bool:
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


def external_deployment_command_summary(commands: list[str]) -> str:
    if not commands:
        return "-"
    if len(commands) == 1:
        return commands[0]
    return f"{commands[0]}\n另有 {len(commands) - 1} 個 smoke 指令，見下方單項診斷指令。"


def external_smoke_commands_from_payload(payload: object) -> list[str]:
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


def _service_snapshot_external_env_items(service_snapshot: dict) -> list[dict]:
    if not isinstance(service_snapshot, dict):
        return []
    items: list[dict] = []
    graph = (
        service_snapshot.get("supply_chain_graph")
        if isinstance(service_snapshot.get("supply_chain_graph"), dict)
        else {}
    )
    neo4j_import = (
        graph.get("neo4j_import") if isinstance(graph.get("neo4j_import"), dict) else {}
    )
    if neo4j_import and not neo4j_import.get("ready"):
        items.append(
            {
                "area": "ai_rag",
                "capability": "neo4j_import",
                "label": "Neo4j / GraphRAG live graph",
                "status": "degraded",
                "severity": "warn",
                "external_integration": True,
                "deployment_check": True,
                "evidence": neo4j_import,
                "remediation": "設定 NEO4J_URI / 帳密並啟動 Neo4j。",
                "_env_source": "/services/status",
            }
        )
    filings = (
        service_snapshot.get("company_filings")
        if isinstance(service_snapshot.get("company_filings"), dict)
        else {}
    )
    if not filings:
        return items
    items.extend(_company_filing_env_items(filings))
    return items


def _company_filing_env_items(filings: dict) -> list[dict]:
    items: list[dict] = []
    browser_runtime = (
        filings.get("browser_render_runtime")
        if isinstance(filings.get("browser_render_runtime"), dict)
        else {}
    )
    if browser_runtime and not browser_runtime.get("configuration_ready"):
        items.append(
            _service_env_item(
                "company_filing_browser_or_proxy_fallback",
                "公司文件 Browser render 後援",
                browser_runtime,
                "補齊 Browser render provider / URL 後重跑文件 render smoke。",
            )
        )
    high_risk_policy = (
        filings.get("high_risk_source_policy")
        if isinstance(filings.get("high_risk_source_policy"), dict)
        else {}
    )
    if high_risk_policy and not high_risk_policy.get("high_risk_mitigation_ready"):
        items.append(
            _service_env_item(
                "company_filing_high_risk_unlocker",
                "MOPS/TWSE/TPEx 高風險文件 unlocker",
                high_risk_policy,
                "設定 FlareSolverr、ScrapingBee、BrightData 或 rotating proxy。",
                optional=True,
            )
        )
    structured_runtime = (
        filings.get("structured_api_runtime")
        if isinstance(filings.get("structured_api_runtime"), dict)
        else {}
    )
    if structured_runtime and not structured_runtime.get("configuration_ready"):
        items.append(
            _service_env_item(
                "company_filing_structured_api_fallback",
                "公司文件結構化 API 備援",
                {"runtime": structured_runtime},
                "設定 TEJ 或專業資料 API provider / URL / token。",
                optional=True,
            )
        )
    visual_runtime = (
        filings.get("visual_rag_runtime")
        if isinstance(filings.get("visual_rag_runtime"), dict)
        else {}
    )
    if visual_runtime and not visual_runtime.get("runtime_available"):
        items.append(
            {
                "area": "ai_rag",
                "capability": "visual_rag",
                "label": "Visual RAG / VLM 財報解析",
                "status": "not_configured",
                "severity": "warn",
                "optional": True,
                "external_integration": True,
                "deployment_check": True,
                "evidence": visual_runtime,
                "remediation": "確認 PyMuPDF、Visual RAG model 與 Gemini key pool。",
                "_env_source": "/services/status",
            }
        )
    return items


def _service_env_item(
    capability: str,
    label: str,
    evidence: dict,
    remediation: str,
    *,
    optional: bool = False,
) -> dict:
    return {
        "area": "data_business_logic",
        "capability": capability,
        "label": label,
        "status": "not_configured",
        "severity": "warn",
        "optional": optional,
        "external_integration": True,
        "deployment_check": True,
        "evidence": evidence,
        "remediation": remediation,
        "_env_source": "/services/status",
    }


def _is_external_readiness_item(item: dict) -> bool:
    if not item.get("external_integration"):
        return False
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    return bool(item.get("deployment_check") or key in EXTERNAL_READINESS_METADATA)


def _external_readiness_sort_key(item: dict, index: int) -> tuple[int, int, int]:
    severity_order = {"fail": 0, "warn": 1, "pass": 2}
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    metadata = external_deployment_readiness_metadata(item)
    return (
        severity_order.get(str(item.get("severity") or ""), 3),
        priority_order.get(metadata["priority"], 4),
        index,
    )


def _external_env_key_row_sort_key(row: dict) -> tuple[int, int, str, str]:
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    status_order = {"缺少": 0, "建議": 1}
    return (
        priority_order.get(str(row.get("優先級") or ""), 4),
        status_order.get(str(row.get("狀態") or ""), 2),
        str(row.get("能力") or ""),
        str(row.get("設定鍵") or ""),
    )


def _external_env_summary(item: dict) -> dict:
    payload = item.get("evidence") if isinstance(item.get("evidence"), dict) else item
    return {
        "missing": set(_collect_named_string_lists(payload, {"missing_env_keys"})),
        "configured": set(_collect_named_string_lists(payload, {"configured_env_keys"})),
        "required": set(
            _collect_named_string_lists(payload, {"required_env_keys", "env_keys"})
        ),
        "recommended": _collect_env_recommendations(payload),
        "fallback_reasons": set(
            _collect_named_strings(
                payload,
                {"fallback_reason", "reason", "connection_error", "runtime_error"},
            )
        ),
    }


def _external_env_key_actions(item: dict, env_summary: dict) -> list[tuple[str, str]]:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    missing = set(env_summary["missing"])
    configured = set(env_summary["configured"])
    recommended = set(env_summary["recommended"])
    defaults = set(EXTERNAL_CAPABILITY_ENV_DEFAULTS.get(key, ()))
    actions: list[tuple[str, str]] = []
    if _external_env_missing_neo4j_uri(key, env_summary):
        missing.add("NEO4J_URI")
    for env_key in sorted(missing - configured):
        actions.append((env_key, "缺少"))
    if _external_env_needs_default_keys(item, env_summary):
        for env_key in sorted((defaults or env_summary["required"]) - configured - missing):
            actions.append((env_key, "建議"))
    for env_key in sorted(recommended - configured - missing):
        if defaults and env_key not in defaults:
            continue
        actions.append((env_key, "建議"))
    return actions


def _external_env_missing_neo4j_uri(key: tuple[str, str], env_summary: dict) -> bool:
    if key not in {
        ("ai_rag", "neo4j_import"),
        ("ai_rag", "graphrag_live_cypher_query"),
    }:
        return False
    return any(
        str(reason).startswith("missing_settings:neo4j_uri")
        for reason in env_summary["fallback_reasons"]
    )


def _external_env_needs_default_keys(item: dict, env_summary: dict) -> bool:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    fallback_reasons = env_summary["fallback_reasons"]
    if key in {
        ("ai_rag", "neo4j_import"),
        ("ai_rag", "graphrag_live_cypher_query"),
    }:
        return any(
            str(reason).startswith("missing_settings:neo4j")
            for reason in fallback_reasons
        )
    if key == ("ai_rag", "visual_rag"):
        return any(
            "missing_vision_llm_key_or_gateway" in str(reason)
            for reason in fallback_reasons
        )
    return False


def _external_env_key_next_step(item: dict, env_key: str, status: str) -> str:
    remediation = str(item.get("remediation") or "").strip()
    if status == "缺少":
        return f"補齊 {env_key} 後重跑對應 smoke。"
    if remediation:
        return remediation
    return f"需要該能力時設定 {env_key}，再重跑 readiness checklist。"


def _external_env_resolution_type(env_key: str, recommended_value: str) -> str:
    if env_key.endswith("_TOKEN") or env_key.endswith("_PASSWORD") or "API_KEY" in env_key:
        return "需人工密鑰"
    if env_key == "COMPANY_FILING_STRUCTURED_API_PROVIDER":
        return "外部資料源設定"
    if env_key == "COMPANY_FILING_STRUCTURED_API_URL":
        return "外部資料源設定"
    if env_key == "COMPANY_FILING_PROXY_URLS":
        return "外部服務選配"
    if "<" in recommended_value and ">" in recommended_value:
        return "需人工設定"
    return "本機可套用"


def _external_env_maintenance_action(
    item: dict,
    env_key: str,
    recommended_value: str,
    resolution_type: str,
) -> str:
    if resolution_type == "需人工密鑰":
        return "手動補 .env 或 secret manager；不由維護操作寫入。"
    if resolution_type in {"外部資料源設定", "外部服務選配", "需人工設定"}:
        return "手動補 .env 或部署 secret 後重跑外部設定缺口診斷。"
    capability = str(item.get("capability") or "")
    if capability in {"neo4j_import", "graphrag_live_cypher_query"}:
        return ".venv/bin/python scripts/start_system.py --start-dependencies"
    if capability == "company_filing_high_risk_unlocker":
        return ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker"
    if capability == "company_filing_browser_or_proxy_fallback":
        return ".venv/bin/python scripts/start_system.py --start-dependencies"
    if "127.0.0.1" in recommended_value or "localhost" in recommended_value:
        return ".venv/bin/python scripts/start_system.py --start-dependencies"
    return "手動補 .env 或部署 secret 後重跑外部設定缺口診斷。"


def _collect_external_smoke_commands(payload: object, commands: list[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            if (
                key_text in EXTERNAL_SMOKE_COMMAND_KEYS
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


def _collect_named_string_lists(payload: object, keys: set[str]) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) in keys:
                values.extend(string_list(value))
            else:
                values.extend(_collect_named_string_lists(value, keys))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_collect_named_string_lists(value, keys))
    return values


def _collect_named_strings(payload: object, keys: set[str]) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) in keys and str(value or "").strip():
                values.append(str(value).strip())
            else:
                values.extend(_collect_named_strings(value, keys))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_collect_named_strings(value, keys))
    return values


def _collect_env_recommendations(payload: object) -> dict[str, str]:
    recommendations: dict[str, str] = {}
    for line in _collect_named_string_lists(
        payload,
        {"recommended_env", "compose_recommended_env"},
    ):
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.isupper():
            continue
        recommendations.setdefault(
            key,
            value.strip() or EXTERNAL_ENV_KEY_HINTS.get(key, {}).get("default") or "-",
        )
    return recommendations


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
