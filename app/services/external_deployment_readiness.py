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
EXTERNAL_ENABLEMENT_METADATA = {
    ("ai_rag", "neo4j_import"): {
        "group": "free_local_first",
        "group_label": "可本機免費啟用",
        "cost_profile": "free_local_or_managed",
        "cost_label": "本機 Neo4j 免費；託管 Neo4j 依方案",
        "recommended_path": "先啟動本機 Neo4j；正式部署再視流量改託管。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("ai_rag", "graphrag_live_cypher_query"): {
        "group": "free_local_first",
        "group_label": "可本機免費啟用",
        "cost_profile": "free_local_or_managed",
        "cost_label": "本機 Neo4j 免費；託管 Neo4j 依方案",
        "recommended_path": "先用本機 Neo4j 驗證 guarded Cypher；正式部署再接託管圖庫。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("ai_rag", "visual_rag"): {
        "group": "quota_or_local_model",
        "group_label": "API 額度或本機模型",
        "cost_profile": "free_quota_or_paid_tokens",
        "cost_label": "Gemini 免費額度可先用；大量 PDF 圖像解析會消耗額度或 API 成本",
        "recommended_path": "先限制 Visual RAG request budget，只對複雜 PDF 啟用。",
        "free_local_available": False,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_pdf_table_parser_runtime"): {
        "group": "free_python_runtime",
        "group_label": "免費 Python 套件",
        "cost_profile": "free_runtime_dependency",
        "cost_label": "pdfplumber/PyMuPDF 類套件免費；unstructured 可能需要較重系統依賴",
        "recommended_path": "先安裝輕量 parser；只有複雜表格再補 unstructured。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_browser_or_proxy_fallback"): {
        "group": "free_local_first",
        "group_label": "可本機免費啟用",
        "cost_profile": "free_local_or_paid_proxy",
        "cost_label": "Playwright/Browserless 本機免費；rotating proxy 可能付費",
        "recommended_path": "先用 Playwright 或 Browserless；遇到封鎖再加 proxy。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_high_risk_unlocker"): {
        "group": "free_local_or_paid_unlocker",
        "group_label": "本機免費或付費 unlocker",
        "cost_profile": "free_flaresolverr_or_paid_managed",
        "cost_label": "FlareSolverr 本機免費；ScrapingBee/BrightData 通常付費",
        "recommended_path": "先用本機 FlareSolverr；穩定正式部署再評估 managed unlocker。",
        "free_local_available": True,
        "paid_service_required": False,
    },
    ("data_business_logic", "company_filing_structured_api_fallback"): {
        "group": "paid_external_api",
        "group_label": "需外部資料 API",
        "cost_profile": "paid_contract_likely",
        "cost_label": "TEJ 或專業資料商通常需付費合約/API token",
        "recommended_path": (
            "免費版先保留 sample contract，並用本機 fixture API 驗證 live HTTP contract；"
            "只有需要穩定法說/重大訊息才接資料商。"
        ),
        "free_local_available": False,
        "paid_service_required": True,
    },
}


def external_deployment_readiness_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for item in external_deployment_readiness_items(upgrade_audit):
        metadata = external_deployment_readiness_metadata(item)
        enablement = external_deployment_enablement_profile(item)
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
                "啟用分類": enablement["group_label"],
                "成本/額度": enablement["cost_label"],
                "建議路徑": enablement["recommended_path"],
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


def external_deployment_enablement_summary(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> dict:
    items = external_deployment_readiness_items(upgrade_audit)
    groups: dict[str, dict] = {}
    summary = {
        "total": len(items),
        "ready": 0,
        "pending": 0,
        "free_local_pending": 0,
        "local_action_available": 0,
        "quota_or_external_pending": 0,
        "paid_external_pending": 0,
        "manual_or_paid_pending": 0,
        "blocking_pending": 0,
        "nonblocking_optional_pending": 0,
        "all_pending_optional": False,
        "paid_external_only_pending": False,
        "groups": [],
        "primary_next_action": "",
    }
    for item in items:
        ready = external_deployment_item_ready(item)
        enablement = external_deployment_enablement_profile(item)
        local_action = external_deployment_local_action(
            item,
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
        group = _external_enablement_group_entry(groups, enablement)
        group["total"] += 1
        if ready:
            summary["ready"] += 1
            group["ready"] += 1
            continue

        summary["pending"] += 1
        group["pending"] += 1
        item_label = str(item.get("label") or item.get("capability") or "-")
        group["pending_items"].append(item_label)
        if item.get("optional") or item.get("_warning_source") == "optional_warnings":
            summary["nonblocking_optional_pending"] += 1
        else:
            summary["blocking_pending"] += 1
        deployment_profile = str(enablement.get("deployment_profile") or "")
        if deployment_profile == "free_local":
            summary["free_local_pending"] += 1
        elif deployment_profile == "paid_external":
            summary["paid_external_pending"] += 1
        else:
            summary["quota_or_external_pending"] += 1
        if local_action.get("state") in {
            "可啟動",
            "已啟動",
            "端口已啟動，需驗證",
            "驗證失敗",
        } and (local_action.get("command") != "-"):
            summary["local_action_available"] += 1

    summary["manual_or_paid_pending"] = (
        summary["quota_or_external_pending"] + summary["paid_external_pending"]
    )
    summary["all_pending_optional"] = bool(
        summary["pending"] > 0
        and summary["blocking_pending"] == 0
        and summary["nonblocking_optional_pending"] == summary["pending"]
    )
    summary["paid_external_only_pending"] = bool(
        summary["pending"] > 0
        and summary["paid_external_pending"] == summary["pending"]
        and summary["free_local_pending"] == 0
        and summary["quota_or_external_pending"] == 0
    )
    summary["groups"] = _external_enablement_summary_groups(groups)
    summary["primary_next_action"] = _external_enablement_primary_next_action(summary)
    return summary


def external_deployment_enablement_summary_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    summary = external_deployment_enablement_summary(
        upgrade_audit,
        local_dependency_status=local_dependency_status,
    )
    rows = []
    for group in summary.get("groups") or []:
        pending_items = [str(item) for item in group.get("pending_items") or []]
        rows.append(
            {
                "分類": group.get("label") or group.get("group") or "-",
                "待處理": int(group.get("pending") or 0),
                "已就緒": int(group.get("ready") or 0),
                "成本/額度": group.get("cost_label") or "-",
                "建議路徑": group.get("recommended_path") or "-",
                "待處理項目": "、".join(pending_items[:4]) if pending_items else "-",
            }
        )
    return rows


def external_deployment_pending_gap_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for item in external_deployment_readiness_items(upgrade_audit):
        if external_deployment_item_ready(item):
            continue
        metadata = external_deployment_readiness_metadata(item)
        enablement = external_deployment_enablement_profile(item)
        local_action = external_deployment_local_action(
            item,
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
        rows.append(
            {
                "priority": metadata["priority"],
                "area": str(item.get("area") or ""),
                "area_label": _external_area_label(item),
                "capability": str(item.get("capability") or ""),
                "label": str(item.get("label") or item.get("capability") or "-"),
                "status": str(item.get("status") or "-"),
                "severity": str(item.get("severity") or "warn"),
                "decision": external_deployment_readiness_decision(item),
                "action_type": _external_gap_action_type(enablement, local_action),
                "deployment_profile": enablement["deployment_profile"],
                "enablement_group": enablement["group"],
                "enablement_label": enablement["group_label"],
                "free_local_available": enablement["free_local_available"],
                "paid_service_required": enablement["paid_service_required"],
                "local_action_state": local_action["state"],
                "local_action_command": local_action["command"],
                "cost_label": enablement["cost_label"],
                "recommended_path": enablement["recommended_path"],
                "remediation": item.get("remediation") or "-",
                "detail": _external_warning_detail(item),
                "smoke_commands": external_smoke_commands_from_payload(item),
            }
        )
    return sorted(rows, key=_external_pending_gap_sort_key)


def external_deployment_pending_gap_display_rows(
    upgrade_audit: dict,
    local_dependency_status: dict | None = None,
) -> list[dict]:
    return [
        {
            "優先級": row["priority"],
            "能力": row["label"],
            "處理類型": _external_gap_action_label(row["action_type"]),
            "狀態": row["status"],
            "部署決策": row["decision"],
            "啟用分類": row["enablement_label"],
            "本機動作": row["local_action_state"],
            "本機指令": row["local_action_command"],
            "成本/額度": row["cost_label"],
            "建議路徑": row["recommended_path"],
        }
        for row in external_deployment_pending_gap_rows(
            upgrade_audit,
            local_dependency_status=local_dependency_status,
        )
    ]


def external_deployment_pending_gap_action_counts(rows: list[dict]) -> dict[str, int]:
    counts = {
        "local_action": 0,
        "quota_or_external": 0,
        "paid_external": 0,
        "manual_configuration": 0,
    }
    for row in rows:
        action_type = str(row.get("action_type") or "manual_configuration")
        counts[action_type] = counts.get(action_type, 0) + 1
    return counts


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


def external_deployment_enablement_profile(item: dict) -> dict:
    key = (str(item.get("area") or ""), str(item.get("capability") or ""))
    metadata = EXTERNAL_ENABLEMENT_METADATA.get(key, {})
    free_local_available = bool(metadata.get("free_local_available"))
    paid_service_required = bool(metadata.get("paid_service_required"))
    return {
        "group": str(metadata.get("group") or "external_configuration"),
        "group_label": str(metadata.get("group_label") or "需外部設定"),
        "cost_profile": str(metadata.get("cost_profile") or "unknown"),
        "cost_label": str(metadata.get("cost_label") or "依外部服務設定而定"),
        "recommended_path": str(
            metadata.get("recommended_path") or item.get("remediation") or "-"
        ),
        "free_local_available": free_local_available,
        "paid_service_required": paid_service_required,
        "deployment_profile": (
            "free_local"
            if free_local_available and not paid_service_required
            else "paid_external"
            if paid_service_required
            else "quota_or_external"
        ),
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
    item_ready = _external_readiness_item_ready(item)
    if wait_key and wait_key in wait_status:
        return {
            "state": _external_local_ready_state(item_ready)
            if wait_status.get(wait_key) is True
            else "驗證失敗",
            "command": verify_command,
        }
    port_state = _local_dependency_port_state(local_dependency_status, wait_key)
    if port_state is True:
        return {"state": _external_local_ready_state(item_ready), "command": verify_command}
    if item_ready:
        return {"state": "已啟動", "command": verify_command}
    return {
        "state": "可啟動",
        "command": str(metadata.get("start_command") or verify_command or "-"),
    }


def _external_local_ready_state(item_ready: bool) -> str:
    return "已啟動" if item_ready else "端口已啟動，需驗證"


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
    rows: list[dict] = []
    for item in external_deployment_warning_items(upgrade_audit):
        enablement = external_deployment_enablement_profile(item)
        rows.append(
            {
                "面向": _external_area_label(item),
                "能力": item.get("label") or item.get("capability") or "-",
                "狀態": item.get("status") or "-",
                "警示層級": _external_warning_level(item),
                "啟用分類": enablement["group_label"],
                "成本/額度": enablement["cost_label"],
                "說明": _external_warning_detail(item),
                "診斷指令": "\n".join(external_smoke_commands_from_payload(item)) or "-",
                "處理方向": item.get("remediation") or "-",
            }
        )
    return rows


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


def _external_enablement_group_entry(groups: dict[str, dict], enablement: dict) -> dict:
    group_key = str(enablement.get("group") or "external_configuration")
    if group_key not in groups:
        groups[group_key] = {
            "group": group_key,
            "label": str(enablement.get("group_label") or "需外部設定"),
            "cost_profile": str(enablement.get("cost_profile") or "unknown"),
            "cost_label": str(enablement.get("cost_label") or "依外部服務設定而定"),
            "recommended_path": str(enablement.get("recommended_path") or "-"),
            "free_local_available": bool(enablement.get("free_local_available")),
            "paid_service_required": bool(enablement.get("paid_service_required")),
            "deployment_profile": str(enablement.get("deployment_profile") or ""),
            "total": 0,
            "ready": 0,
            "pending": 0,
            "pending_items": [],
        }
    return groups[group_key]


def _external_enablement_summary_groups(groups: dict[str, dict]) -> list[dict]:
    return [
        groups[key]
        for key in sorted(
            groups,
            key=lambda group_key: _external_enablement_group_sort_key(groups[group_key]),
        )
    ]


def _external_enablement_group_sort_key(group: dict) -> tuple[int, str]:
    profile_order = {"free_local": 0, "quota_or_external": 1, "paid_external": 2}
    deployment_profile = str(group.get("deployment_profile") or "")
    return (
        profile_order.get(deployment_profile, 3),
        str(group.get("label") or group.get("group") or ""),
    )


def _external_enablement_primary_next_action(summary: dict) -> str:
    if int(summary.get("pending") or 0) <= 0:
        return "外部部署選配皆已就緒。"
    if int(summary.get("local_action_available") or 0) > 0:
        return "先處理本機免費可補強項目，再評估 API 額度或付費資料商。"
    if summary.get("paid_external_only_pending"):
        return "剩餘項目都是付費外部 API 或資料商選配；免費版可先維持 sample contract。"
    if int(summary.get("paid_external_pending") or 0) > 0:
        return "剩餘項目需要外部資料 API 或服務合約，免費版可先保留 sample contract。"
    if int(summary.get("quota_or_external_pending") or 0) > 0:
        return "剩餘項目主要取決於模型/API 額度，建議只在高價值文件啟用。"
    return "依 readiness checklist 逐項補齊設定。"


def _external_gap_action_type(enablement: dict, local_action: dict) -> str:
    if (
        enablement.get("deployment_profile") == "free_local"
        and str(local_action.get("command") or "-") != "-"
    ):
        return "local_action"
    if enablement.get("paid_service_required"):
        return "paid_external"
    if enablement.get("deployment_profile") == "quota_or_external":
        return "quota_or_external"
    return "manual_configuration"


def _external_gap_action_label(action_type: object) -> str:
    labels = {
        "local_action": "本機可修",
        "quota_or_external": "額度/外部選配",
        "paid_external": "付費外部 API",
        "manual_configuration": "手動設定",
    }
    return labels.get(str(action_type or ""), str(action_type or "-"))


def _external_pending_gap_sort_key(row: dict) -> tuple[int, int, str]:
    action_order = {
        "local_action": 0,
        "quota_or_external": 1,
        "paid_external": 2,
        "manual_configuration": 3,
    }
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return (
        action_order.get(str(row.get("action_type") or ""), 4),
        priority_order.get(str(row.get("priority") or ""), 4),
        str(row.get("label") or ""),
    )


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
