from __future__ import annotations

from typing import Any

from app.services.external_deployment_env_catalog import (
    EXTERNAL_ENV_CHECK_TARGETS,
    external_capability_env_defaults,
    external_env_compose_recommended_value,
    external_env_key_hint,
)
from app.services.external_deployment_env_templates import (
    external_deployment_env_check_report as external_deployment_env_check_report,
    format_external_deployment_env_template as format_external_deployment_env_template,
    format_external_deployment_env_check_report as format_external_deployment_env_check_report,
)
from app.services.external_deployment_env_resolution import (
    external_deployment_env_resolution_rows_from_key_rows as build_external_deployment_env_resolution_rows,
)
from app.services.external_deployment_readiness import (
    external_deployment_command_summary,
    external_deployment_item_ready,
    external_deployment_readiness_items,
    external_deployment_readiness_metadata,
    external_smoke_commands_from_payload,
    string_list,
)

EXTERNAL_ENV_RESOLUTION_CONTRACT_COLUMNS = ("處理策略", "處理類型", "維護動作")


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
    resolution_rows = external_deployment_env_resolution_rows_from_key_rows(rows)
    return {
        "status": "action_required" if rows else "ready",
        "gap_count": len(rows),
        "missing_count": missing_count,
        "recommended_count": recommended_count,
        "manual_secret_count": manual_secret_count,
        "local_action_count": local_action_count,
        "capability_gap_count": len(resolution_rows),
        "rows": rows,
        "resolution_rows": resolution_rows,
        "local_start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "local_unlocker_start_command": (
            ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker"
        ),
        "strict_external": bool(strict_external),
    }


def external_deployment_env_check_status_report(
    *,
    target: str = "all",
    env_file: str = ".env",
    include_process_env: bool = False,
    strict_external: bool = False,
    upgrade_audit: dict[str, Any] | None = None,
    service_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    targets = _external_env_check_targets(target)
    gap_report = external_deployment_env_gap_report(
        upgrade_audit=upgrade_audit,
        service_snapshot=service_snapshot,
        strict_external=strict_external,
    )
    checks = {
        check_target: external_deployment_env_check_report(
            gap_report,
            target=check_target,
            env_file=env_file,
            include_process_env=include_process_env,
        )
        for check_target in targets
    }
    return {
        "status": _external_env_check_status_from_reports(list(checks.values())),
        "target": "all" if len(targets) > 1 else targets[0],
        "targets": targets,
        "strict_external": bool(strict_external),
        "include_process_env": bool(include_process_env),
        "env_file": env_file,
        "gap_status": gap_report.get("status"),
        "gap_count": gap_report.get("gap_count", 0),
        "checks": checks,
    }


def format_external_deployment_env_check_status_report(report: dict[str, Any]) -> str:
    checks = report.get("checks") or {}
    targets = report.get("targets") or sorted(str(target) for target in checks)
    lines = [
        (
            f"External deployment env check: {report['status']} "
            f"(target={report.get('target', 'all')}; gaps={report.get('gap_count', 0)})"
        )
    ]
    if report.get("env_file"):
        lines.append(f"Env file: {report['env_file']}")
    if not checks:
        lines.append("No external deployment env check details available.")
        return "\n".join(lines)
    for target in targets:
        check = checks.get(str(target)) or {}
        lines.append(
            (
                f"[{target}] {check.get('status', 'unknown')} "
                f"(checked={check.get('checked_count', 0)}; "
                f"missing={check.get('missing_count', 0)}; "
                f"different={check.get('different_count', 0)})"
            )
        )
        if check.get("env_file"):
            exists = "exists" if check.get("env_file_exists") else "missing"
            lines.append(f"  env file: {check['env_file']} ({exists})")
        for row in check.get("rows") or []:
            lines.append(
                f"  - [{row['status']}] {row['env_key']} :: "
                f"expected={row['expected_value']} current={row['current_value']}"
            )
            if row["action"] != "-":
                lines.append(f"    action: {row['action']}")
    return "\n".join(lines)


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
    if report.get("resolution_rows"):
        lines.append("Resolution plan:")
        for row in report["resolution_rows"]:
            lines.append(
                f"- {row['優先級']} {row['能力']} :: {row['處理策略']} "
                f"(gaps={row['缺口數']}; local={row['本機可套用']}; "
                f"manual={row['需人工處理']})"
            )
            lines.append(f"  action: {row['建議動作']}")
            lines.append(f"  keys: {row['設定鍵']}")
            lines.append(f"  verify: {row['驗證指令']}")
    for row in report["rows"]:
        lines.append(
            f"- [{row['狀態']}] {row['優先級']} {row['能力']} :: "
            f"{row['設定鍵']} ({row['處理類型']})"
        )
        lines.append(f"  value: {row['建議值']}")
        lines.append(f"  action: {row['維護動作']}")
        lines.append(f"  verify: {row['驗證指令']}")
    return "\n".join(lines)


def _external_env_check_targets(target: str) -> list[str]:
    normalized = str(target or "all").strip().lower()
    if normalized == "all":
        return list(EXTERNAL_ENV_CHECK_TARGETS)
    if normalized in EXTERNAL_ENV_CHECK_TARGETS:
        return [normalized]
    allowed = ", ".join(("all", *EXTERNAL_ENV_CHECK_TARGETS))
    raise ValueError(f"Unsupported external env check target: {target!r}. Use one of: {allowed}.")


def _external_env_check_status_from_reports(reports: list[dict[str, Any]]) -> str:
    statuses = [str(report.get("status") or "ready") for report in reports]
    if "action_required" in statuses:
        return "action_required"
    if "review_required" in statuses:
        return "review_required"
    return "ready"


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
            hint = external_env_key_hint(env_key)
            recommended_value = (
                env_summary["recommended"].get(env_key) or hint.get("default") or "-"
            )
            compose_recommended_value = external_env_compose_recommended_value(
                env_key,
                recommended_value,
                env_summary["compose_recommended"],
            )
            resolution_type = _external_env_resolution_type(item, env_key, recommended_value)
            rows.append(
                {
                    "優先級": metadata["priority"],
                    "能力": item.get("label") or item.get("capability") or "-",
                    "設定鍵": env_key,
                    "狀態": status,
                    "目前": "未設定" if status == "缺少" else "建議確認",
                    "建議值": recommended_value,
                    "Compose 建議值": compose_recommended_value,
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


def external_deployment_env_resolution_rows(
    upgrade_audit: dict,
    service_snapshot: dict | None = None,
) -> list[dict]:
    return external_deployment_env_resolution_rows_from_key_rows(
        external_deployment_env_key_rows(upgrade_audit, service_snapshot)
    )


def external_deployment_env_resolution_rows_from_key_rows(rows: list[dict]) -> list[dict]:
    return build_external_deployment_env_resolution_rows(rows)


def _ordered_unique(values: object) -> list[str]:
    output: list[str] = []
    for value in values if isinstance(values, list) else list(values or []):
        text = str(value or "").strip()
        if not text or text == "-" or text in output:
            continue
        output.append(text)
    return output


def _service_snapshot_external_env_items(service_snapshot: dict) -> list[dict]:
    if not isinstance(service_snapshot, dict):
        return []
    items: list[dict] = []
    graph = (
        service_snapshot.get("supply_chain_graph")
        if isinstance(service_snapshot.get("supply_chain_graph"), dict)
        else {}
    )
    neo4j_import = graph.get("neo4j_import") if isinstance(graph.get("neo4j_import"), dict) else {}
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
        "required": set(_collect_named_string_lists(payload, {"required_env_keys", "env_keys"})),
        "recommended": _collect_env_recommendations(payload, {"recommended_env"}),
        "compose_recommended": _collect_env_recommendations(
            payload,
            {"compose_recommended_env"},
        ),
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
    defaults = set(external_capability_env_defaults(*key))
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
    for env_key in sorted(recommended & configured):
        if defaults and env_key not in defaults:
            continue
        if _external_env_should_recommend_configured_value(key, env_key):
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
        return any(str(reason).startswith("missing_settings:neo4j") for reason in fallback_reasons)
    if key == ("ai_rag", "visual_rag"):
        return any(
            "missing_vision_llm_key_or_gateway" in str(reason) for reason in fallback_reasons
        )
    return False


def _external_env_should_recommend_configured_value(
    key: tuple[str, str],
    env_key: str,
) -> bool:
    return key == ("data_business_logic", "company_filing_high_risk_unlocker") and env_key in {
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    }


def _external_env_key_next_step(item: dict, env_key: str, status: str) -> str:
    remediation = str(item.get("remediation") or "").strip()
    if status == "缺少":
        return f"補齊 {env_key} 後重跑對應 smoke。"
    if remediation:
        return remediation
    return f"需要該能力時設定 {env_key}，再重跑 readiness checklist。"


def _external_env_resolution_type(item: dict, env_key: str, recommended_value: str) -> str:
    capability = str(item.get("capability") or "")
    if capability in {"neo4j_import", "graphrag_live_cypher_query"}:
        return "本機可套用"
    if capability == "company_filing_high_risk_unlocker" and env_key in {
        "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
        "COMPANY_FILING_BROWSER_RENDER_URL",
    }:
        if (
            "flaresolverr" in recommended_value
            or "127.0.0.1" in recommended_value
            or "localhost" in recommended_value
        ):
            return "本機可套用"
        return "外部服務選配"
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


def _collect_env_recommendations(
    payload: object,
    keys: set[str] | None = None,
) -> dict[str, str]:
    recommendations: dict[str, str] = {}
    for line in _collect_named_string_lists(
        payload,
        keys or {"recommended_env", "compose_recommended_env"},
    ):
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.isupper():
            continue
        recommendations.setdefault(
            key,
            value.strip() or external_env_key_hint(key).get("default") or "-",
        )
    return recommendations
