from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.optimization_free_validation import capability_free_validation
from app.services.optimization_action_priority import (
    prioritized_optimization_next_actions,
)
from app.services.optimization_local_defaults import (
    AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND,
    EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND as EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND,
    EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND as EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND,
    LOCAL_BROWSER_RENDER_DEFAULTS_AUDIT_COMMAND as LOCAL_BROWSER_RENDER_DEFAULTS_AUDIT_COMMAND,
    LOCAL_FLARESOLVERR_DEFAULTS_AUDIT_COMMAND as LOCAL_FLARESOLVERR_DEFAULTS_AUDIT_COMMAND,
    LOCAL_NEO4J_DEFAULTS_AUDIT_COMMAND as LOCAL_NEO4J_DEFAULTS_AUDIT_COMMAND,
    local_default_capabilities,
    local_default_verify_commands,
    local_defaults_verify_command,
)


@dataclass(frozen=True)
class OptimizationCapabilityRef:
    area: str
    capability: str
    label: str
    optional: bool = False
    external: bool = False
    action_type: str = "code_or_config"
    next_action: str = ""


@dataclass(frozen=True)
class OptimizationDomain:
    id: str
    label: str
    objective: str
    capability_refs: tuple[OptimizationCapabilityRef, ...]
    long_term_note: str = ""


OPTIMIZATION_DOMAINS: tuple[OptimizationDomain, ...] = (
    OptimizationDomain(
        id="architecture_uiux",
        label="系統架構與前端體驗",
        objective="Streamlit MPA、外部 CSS、FastAPI/Celery 背景任務輪詢與可恢復 workflow。",
        capability_refs=(
            OptimizationCapabilityRef(
                "architecture",
                "streamlit_mpa_background_tasks",
                "Streamlit MPA 與背景任務輪詢",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "background_task_queue",
                "背景任務 queue readiness",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "workflow_orchestration",
                "可恢復 workflow orchestration",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "latest_report_retention",
                "最新版報告保留策略",
            ),
        ),
        long_term_note="若正式開放多人使用，再評估把 Streamlit 前端遷移到 Next.js/Nuxt。",
    ),
    OptimizationDomain(
        id="codebase_maintainability",
        label="程式碼結構與維護性",
        objective="API controller 維持 thin entry，業務邏輯下放 service，安全掃描使用外部工具。",
        capability_refs=(
            OptimizationCapabilityRef(
                "architecture",
                "thin_api_controller",
                "API controller/service 分層",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "database_migrations",
                "Alembic database migrations",
            ),
            OptimizationCapabilityRef(
                "architecture",
                "secret_scanning",
                "外部密鑰掃描工具整合",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "source_quality_weighting",
                "來源可信度分層與低品質來源降權",
            ),
        ),
        long_term_note="Legacy alias 只保留相容舊測試/腳本；新功能應繼續從 router 呼叫 service/use case。",
    ),
    OptimizationDomain(
        id="data_pipeline_scraping",
        label="資料管線與爬蟲穩定度",
        objective="市場資料快取/來源 fallback、公司文件 render/unlocker、官方 OpenAPI 與結構化 API 備援。",
        capability_refs=(
            OptimizationCapabilityRef(
                "data_business_logic",
                "market_data_cache",
                "Redis 市場/財務資料快取",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "market_data_provider_fallback",
                "FinMind/Fugle/官方 OpenAPI fallback",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_fetch_hardening",
                "公司文件反爬蟲與 PDF/HTML 表格解析",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_render_provider_contract",
                "公司文件 render/unlocker provider contract",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_official_material_information_openapi",
                "TWSE/TPEx 官方重大訊息 OpenAPI fallback",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_structured_api_sample_contract",
                "公司文件結構化 API sample contract",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_cache",
                "公司文件 URL 解析快取",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_browser_or_proxy_fallback",
                "公司文件 Proxy / Browser render / Playwright 後援",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="正式部署若常遇到動態頁或空殼頁，再設定 Browserless/Proxy/Playwright。",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_high_risk_unlocker",
                "MOPS/TWSE/TPEx 高風險文件 unlocker",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="高風險 MOPS/TWSE 文件被擋時，優先啟用 FlareSolverr，再評估 ScrapingBee/BrightData。",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_structured_api_fallback",
                "公司文件結構化 API 備援",
                optional=True,
                external=True,
                action_type="paid_external",
                next_action="只有需要穩定法說會簡報/重大訊息時，才接 TEJ 或專業資料 API。",
            ),
            OptimizationCapabilityRef(
                "data_business_logic",
                "company_filing_pdf_table_parser_runtime",
                "PDF 表格 parser runtime",
                optional=True,
                action_type="local_dependency",
                next_action='需要更多 PDF 表格抽取時安裝 pip install -e ".[pdf]"。',
            ),
        ),
    ),
    OptimizationDomain(
        id="ai_rag_graphrag",
        label="AI、RAG 與知識圖譜",
        objective="免費額度感知模型路由、hybrid retrieval/reranker、GraphRAG 推理、Visual RAG 與 observability。",
        capability_refs=(
            OptimizationCapabilityRef(
                "ai_rag",
                "multilingual_embedding",
                "明確使用繁中/多語 embedding",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "llm_sdk_and_fallback",
                "LLM SDK 與模型降級能力",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "llm_quota_routing",
                "免費額度感知模型路由",
            ),
            OptimizationCapabilityRef("ai_rag", "hybrid_search", "Hybrid Search / BM25 關鍵字檢索"),
            OptimizationCapabilityRef("ai_rag", "reranking", "模型級 reranking"),
            OptimizationCapabilityRef("ai_rag", "llm_observability", "LLM/RAG observability"),
            OptimizationCapabilityRef("ai_rag", "graphrag_context", "GraphRAG 檢索脈絡"),
            OptimizationCapabilityRef(
                "ai_rag",
                "graphrag_path_reasoning",
                "GraphRAG shortest-path 推理脈絡",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "graphrag_agentic_cypher",
                "GraphRAG guarded LLM Cypher planner",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "neo4j_payload_export",
                "Neo4j parameterized payload export",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "visual_rag",
                "Visual RAG / VLM 財報解析",
                optional=True,
                external=True,
                action_type="quota_or_external",
                next_action="需要處理掃描型或複雜表格 PDF 時，再配置 vision-capable 模型與額度。",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "neo4j_import",
                "外部 Neo4j 匯入連線",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="正式部署需要 live graph import 時，設定 Neo4j URI/帳密並跑 smoke。",
            ),
            OptimizationCapabilityRef(
                "ai_rag",
                "graphrag_live_cypher_query",
                "GraphRAG guarded live Cypher query",
                optional=True,
                external=True,
                action_type="free_local_or_external_config",
                next_action="正式部署要讓 guarded Cypher 直接查 Neo4j 時，再啟用 live query。",
            ),
        ),
    ),
)

READY_STATUSES = frozenset({"ready"})


def optimization_progress_status(status: dict) -> dict:
    matrix = status.get("upgrade_capability_matrix") or {}
    local_auto_defaults = _local_auto_defaults(status)
    domains = [
        _domain_status(domain, matrix, local_auto_defaults) for domain in OPTIMIZATION_DOMAINS
    ]
    blocking_gap_count = sum(int(domain["blocking_gap_count"]) for domain in domains)
    optional_gap_count = sum(int(domain["optional_gap_count"]) for domain in domains)
    local_resolvable_gap_count = sum(
        int(domain["local_resolvable_gap_count"]) for domain in domains
    )
    projected_blocking_gap_count = sum(
        int(domain["projected_blocking_gap_count"]) for domain in domains
    )
    projected_optional_gap_count = sum(
        int(domain["projected_optional_gap_count"]) for domain in domains
    )
    total_checks = sum(int(domain["total_checks"]) for domain in domains)
    ready_checks = sum(int(domain["ready_checks"]) for domain in domains)
    overall_status = _overall_status(blocking_gap_count, optional_gap_count)
    projected_status = _overall_status(
        projected_blocking_gap_count,
        projected_optional_gap_count,
    )
    effective_blocking_gap_count = _effective_gap_count(
        raw_count=blocking_gap_count,
        projected_count=projected_blocking_gap_count,
        local_resolvable_gap_count=local_resolvable_gap_count,
    )
    effective_optional_gap_count = _effective_gap_count(
        raw_count=optional_gap_count,
        projected_count=projected_optional_gap_count,
        local_resolvable_gap_count=local_resolvable_gap_count,
    )
    effective_status = projected_status if local_resolvable_gap_count > 0 else overall_status
    next_actions = _next_actions(domains)
    prioritized_next_actions = prioritized_optimization_next_actions(next_actions)
    local_projection = _local_resolution_projection(
        projected_status=projected_status,
        local_resolvable_gap_count=local_resolvable_gap_count,
        projected_blocking_gap_count=projected_blocking_gap_count,
        projected_optional_gap_count=projected_optional_gap_count,
        prioritized_next_actions=prioritized_next_actions,
    )
    primary_next_action = _primary_next_action(
        overall_status,
        prioritized_next_actions,
        optional_gap_count=optional_gap_count,
        local_resolvable_gap_count=local_resolvable_gap_count,
        projected_optional_gap_count=projected_optional_gap_count,
        local_defaults_verify_command=str(
            local_projection.get("local_defaults_verify_command") or ""
        ),
    )
    completion_ratio = _ratio(ready_checks, total_checks)
    return {
        "collector_path": "app/services/optimization_progress.py",
        "status": overall_status,
        "projected_status_after_local_defaults": projected_status,
        "total_domains": len(domains),
        "total_checks": total_checks,
        "ready_checks": ready_checks,
        "blocking_gap_count": blocking_gap_count,
        "optional_gap_count": optional_gap_count,
        "local_resolvable_gap_count": local_resolvable_gap_count,
        "effective_status_after_available_local_defaults": effective_status,
        "effective_blocking_gap_count_after_available_local_defaults": (
            effective_blocking_gap_count
        ),
        "effective_optional_gap_count_after_available_local_defaults": (
            effective_optional_gap_count
        ),
        "projected_blocking_gap_count_after_local_defaults": projected_blocking_gap_count,
        "projected_optional_gap_count_after_local_defaults": projected_optional_gap_count,
        "completion_ratio": completion_ratio,
        "summary": _progress_summary(
            overall_status=overall_status,
            effective_status=effective_status,
            total_domains=len(domains),
            total_checks=total_checks,
            ready_checks=ready_checks,
            completion_ratio=completion_ratio,
            blocking_gap_count=blocking_gap_count,
            optional_gap_count=optional_gap_count,
            local_resolvable_gap_count=local_resolvable_gap_count,
            effective_blocking_gap_count=effective_blocking_gap_count,
            effective_optional_gap_count=effective_optional_gap_count,
            projected_blocking_gap_count=projected_blocking_gap_count,
            projected_optional_gap_count=projected_optional_gap_count,
            primary_next_action=primary_next_action,
        ),
        "domains": domains,
        "primary_next_action": primary_next_action,
        "next_actions": next_actions,
        "prioritized_next_actions": prioritized_next_actions,
        "local_defaults_verify_command": (
            local_projection.get("local_defaults_verify_command") or ""
        ),
        "local_default_verify_commands": (
            local_projection.get("local_default_verify_commands") or []
        ),
        "local_resolution_projection": local_projection,
        "status_note": _status_note(overall_status),
        "effective_gap_note": _effective_gap_note(
            raw_blocking_gap_count=blocking_gap_count,
            raw_optional_gap_count=optional_gap_count,
            effective_blocking_gap_count=effective_blocking_gap_count,
            effective_optional_gap_count=effective_optional_gap_count,
            local_resolvable_gap_count=local_resolvable_gap_count,
        ),
        "local_auto_defaults": _local_auto_defaults_summary(local_auto_defaults),
    }


def _domain_status(
    domain: OptimizationDomain,
    matrix: dict,
    local_auto_defaults: dict,
) -> dict:
    checks = [_capability_check(ref, matrix, local_auto_defaults) for ref in domain.capability_refs]
    ready_checks = sum(1 for check in checks if check["ready"])
    blocking_gaps = [check for check in checks if not check["ready"] and not check["optional"]]
    optional_gaps = [check for check in checks if not check["ready"] and check["optional"]]
    local_resolvable_gaps = [
        check for check in [*blocking_gaps, *optional_gaps] if check.get("locally_available")
    ]
    projected_blocking_gaps = [
        check for check in blocking_gaps if not check.get("locally_available")
    ]
    projected_optional_gaps = [
        check for check in optional_gaps if not check.get("locally_available")
    ]
    domain_status = _overall_status(len(blocking_gaps), len(optional_gaps))
    projected_status = _overall_status(
        len(projected_blocking_gaps),
        len(projected_optional_gaps),
    )
    return {
        "id": domain.id,
        "label": domain.label,
        "objective": domain.objective,
        "status": domain_status,
        "projected_status_after_local_defaults": projected_status,
        "total_checks": len(checks),
        "ready_checks": ready_checks,
        "blocking_gap_count": len(blocking_gaps),
        "optional_gap_count": len(optional_gaps),
        "local_resolvable_gap_count": len(local_resolvable_gaps),
        "projected_blocking_gap_count": len(projected_blocking_gaps),
        "projected_optional_gap_count": len(projected_optional_gaps),
        "completion_ratio": _ratio(ready_checks, len(checks)),
        "checks": checks,
        "blocking_gaps": blocking_gaps,
        "optional_gaps": optional_gaps,
        "local_resolvable_gaps": local_resolvable_gaps,
        "projected_remaining_gaps": [*projected_blocking_gaps, *projected_optional_gaps],
        "next_action": _domain_next_action(domain, blocking_gaps, optional_gaps),
        "long_term_note": domain.long_term_note,
    }


def _capability_check(
    ref: OptimizationCapabilityRef,
    matrix: dict,
    local_auto_defaults: dict,
) -> dict:
    capability = _matrix_capability(matrix, ref.area, ref.capability)
    capability_status = str(capability.get("status") or "missing")
    ready = capability_status in READY_STATUSES
    local_match = _local_auto_default_match(ref, local_auto_defaults)
    locally_available = bool(local_match and not ready)
    free_validation = capability_free_validation(capability)
    return {
        "area": ref.area,
        "capability": ref.capability,
        "label": ref.label,
        "status": "local_ready" if locally_available else capability_status,
        "capability_status": capability_status,
        "ready": ready,
        "optional": ref.optional,
        "external": ref.external,
        "action_type": ref.action_type,
        "next_action": _next_action_for_capability(
            ref,
            capability,
            local_match=local_match,
            locally_available=locally_available,
        ),
        "detail": capability.get("detail"),
        "locally_available": locally_available,
        "local_auto_default": local_match or {},
        "free_validation_available": free_validation["available"],
        "free_validation_label": free_validation["label"],
        "free_validation_commands": free_validation["commands"],
    }


def _matrix_capability(matrix: dict, area: str, capability: str) -> dict:
    area_payload = matrix.get(area) if isinstance(matrix.get(area), dict) else {}
    payload = area_payload.get(capability) if isinstance(area_payload.get(capability), dict) else {}
    return payload


def _domain_next_action(
    domain: OptimizationDomain,
    blocking_gaps: list[dict],
    optional_gaps: list[dict],
) -> str:
    if blocking_gaps:
        return str(blocking_gaps[0]["next_action"])
    if optional_gaps:
        return str(optional_gaps[0]["next_action"])
    if domain.long_term_note:
        return domain.long_term_note
    return "目前沒有需要立即改程式的缺口；以觀測、額度與資料品質回歸檢查為主。"


def _next_actions(domains: list[dict]) -> list[dict]:
    actions: list[dict] = []
    for domain in domains:
        for gap_type in ("blocking_gaps", "optional_gaps"):
            for gap in domain.get(gap_type) or []:
                actions.append(
                    {
                        "domain_id": domain["id"],
                        "domain_label": domain["label"],
                        "capability": gap["capability"],
                        "label": gap["label"],
                        "status": gap["status"],
                        "optional": gap["optional"],
                        "external": gap["external"],
                        "action_type": gap["action_type"],
                        "next_action": gap["next_action"],
                        "capability_status": gap.get("capability_status"),
                        "locally_available": gap.get("locally_available"),
                        "local_auto_default": gap.get("local_auto_default") or {},
                        "free_validation_available": bool(gap.get("free_validation_available")),
                        "free_validation_label": gap.get("free_validation_label") or "",
                        "free_validation_commands": gap.get("free_validation_commands") or [],
                    }
                )
    return actions


def _local_resolution_projection(
    *,
    projected_status: str,
    local_resolvable_gap_count: int,
    projected_blocking_gap_count: int,
    projected_optional_gap_count: int,
    prioritized_next_actions: list[dict],
) -> dict:
    remaining_actions = [
        action for action in prioritized_next_actions if not bool(action.get("locally_available"))
    ]
    local_actions = [
        action for action in prioritized_next_actions if bool(action.get("locally_available"))
    ]
    local_defaults_command = local_defaults_verify_command(local_actions)
    local_default_commands = local_default_verify_commands(
        local_defaults_command,
        local_actions,
    )
    if local_resolvable_gap_count <= 0:
        next_action = "沒有偵測到可用本機 defaults；依一般優先隊列處理剩餘缺口。"
    elif projected_blocking_gap_count == 0 and projected_optional_gap_count == 0:
        next_action = (
            f"套用本機 defaults 可消除 {local_resolvable_gap_count} 項剩餘缺口；"
            "之後只需維持 smoke/audit 觀測。"
        )
    elif projected_blocking_gap_count == 0:
        next_action = (
            f"套用本機 defaults 可先消除 {local_resolvable_gap_count} 項缺口；"
            f"之後剩餘 {projected_optional_gap_count} 項外部/付費選配。"
        )
    else:
        next_action = (
            f"套用本機 defaults 可先消除 {local_resolvable_gap_count} 項缺口；"
            f"仍有 {projected_blocking_gap_count} 項 blocking gap 需要處理。"
        )
    return {
        "status_after_local_defaults": projected_status,
        "local_resolvable_gap_count": local_resolvable_gap_count,
        "projected_blocking_gap_count": projected_blocking_gap_count,
        "projected_optional_gap_count": projected_optional_gap_count,
        "remaining_paid_external_pending": sum(
            1 for action in remaining_actions if action.get("action_type") == "paid_external"
        ),
        "local_defaults_verify_command": local_defaults_command,
        "compatible_auto_defaults_verify_command": AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND,
        "local_default_verify_commands": local_default_commands,
        "local_action_capabilities": [
            action.get("capability") for action in local_actions if action.get("capability")
        ],
        "local_default_capabilities": local_default_capabilities(local_actions),
        "remaining_action_capabilities": [
            action.get("capability") for action in remaining_actions if action.get("capability")
        ],
        "remaining_actions": remaining_actions,
        "next_action": next_action,
    }


def _progress_summary(
    *,
    overall_status: str,
    effective_status: str,
    total_domains: int,
    total_checks: int,
    ready_checks: int,
    completion_ratio: float,
    blocking_gap_count: int,
    optional_gap_count: int,
    local_resolvable_gap_count: int,
    effective_blocking_gap_count: int,
    effective_optional_gap_count: int,
    projected_blocking_gap_count: int,
    projected_optional_gap_count: int,
    primary_next_action: dict,
) -> dict:
    return {
        "status": overall_status,
        "effective_status_after_available_local_defaults": effective_status,
        "total_domains": total_domains,
        "total_checks": total_checks,
        "ready_checks": ready_checks,
        "completion_ratio": completion_ratio,
        "blocking_gap_count": blocking_gap_count,
        "optional_gap_count": optional_gap_count,
        "local_resolvable_gap_count": local_resolvable_gap_count,
        "effective_blocking_gap_count_after_available_local_defaults": (
            effective_blocking_gap_count
        ),
        "effective_optional_gap_count_after_available_local_defaults": (
            effective_optional_gap_count
        ),
        "projected_blocking_gap_count_after_local_defaults": (projected_blocking_gap_count),
        "projected_optional_gap_count_after_local_defaults": (projected_optional_gap_count),
        "primary_next_action_label": primary_next_action.get("label") or "",
        "primary_next_action_capability": primary_next_action.get("capability"),
        "primary_next_action_type": primary_next_action.get("action_type") or "",
        "primary_next_action_cost_profile": (primary_next_action.get("cost_profile") or ""),
        "primary_next_action_verify_command": (primary_next_action.get("verify_command") or ""),
    }


def _next_action_for_capability(
    ref: OptimizationCapabilityRef,
    capability: dict[str, Any],
    *,
    local_match: dict | None,
    locally_available: bool,
) -> str:
    if locally_available and local_match:
        command = str(local_match.get("verify_command") or AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND)
        group = str(local_match.get("group") or "local dependency")
        return (
            f"本機 {group} 服務已偵測到；可先用 `{command}` 驗證並套用本次程序 defaults，"
            "正式部署時再寫入 .env。"
        )
    return ref.next_action or _default_next_action(ref, capability)


def _primary_next_action(
    overall_status: str,
    next_actions: list[dict],
    *,
    optional_gap_count: int,
    local_resolvable_gap_count: int,
    projected_optional_gap_count: int,
    local_defaults_verify_command: str,
) -> dict:
    if overall_status == "degraded" and next_actions:
        return next_actions[0]
    if overall_status == "ready_with_optional_gaps":
        if local_resolvable_gap_count > 0:
            command = local_defaults_verify_command or AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND
            return {
                "domain_id": None,
                "domain_label": "全部",
                "capability": "auto_local_defaults",
                "label": "本機 defaults 可驗證",
                "status": "local_ready",
                "optional": True,
                "external": True,
                "action_type": "free_local_or_external_config",
                "locally_available": True,
                "priority_score": 75,
                "priority_band": "free_local_ready",
                "cost_profile": "free_local_available",
                "decision": "先用本機免費服務驗證；正式部署時再固化到 .env。",
                "priority_reason": "本機服務已偵測到，可用一條 audit 指令驗證多個選配缺口。",
                "verify_command": command,
                "next_action": (
                    f"先執行 `{command}`；可用本機 defaults "
                    f"驗證 {local_resolvable_gap_count} 項缺口，之後剩餘 "
                    f"{projected_optional_gap_count} 項外部/付費選配。"
                    f" 相容自動偵測入口：`{AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND}`。"
                ),
            }
        return {
            "domain_id": None,
            "domain_label": "全部",
            "capability": None,
            "label": "核心已完成",
            "status": "ready_with_optional_gaps",
            "optional": True,
            "external": True,
            "action_type": "optional_review",
            "next_action": (
                f"目前沒有 blocking 程式缺口；剩餘 {optional_gap_count} 項依正式部署、"
                "額度或付費資料源需求再啟用。"
            ),
        }
    return _no_gap_action()


def _default_next_action(ref: OptimizationCapabilityRef, capability: dict[str, Any]) -> str:
    detail = str(capability.get("detail") or "").strip()
    if detail:
        return f"檢查 {ref.label}：{detail}"
    return f"檢查 {ref.label} 的設定、依賴與測試證據。"


def _overall_status(blocking_gap_count: int, optional_gap_count: int) -> str:
    if blocking_gap_count:
        return "degraded"
    if optional_gap_count:
        return "ready_with_optional_gaps"
    return "ready"


def _effective_gap_count(
    *,
    raw_count: int,
    projected_count: int,
    local_resolvable_gap_count: int,
) -> int:
    if local_resolvable_gap_count > 0:
        return int(projected_count)
    return int(raw_count)


def _effective_gap_note(
    *,
    raw_blocking_gap_count: int,
    raw_optional_gap_count: int,
    effective_blocking_gap_count: int,
    effective_optional_gap_count: int,
    local_resolvable_gap_count: int,
) -> str:
    if local_resolvable_gap_count <= 0:
        return ""
    return (
        f"原始缺口為 {raw_blocking_gap_count} blocking / {raw_optional_gap_count} 選配；"
        f"本機 defaults 可驗證 {local_resolvable_gap_count} 項後，"
        f"有效剩餘 {effective_blocking_gap_count} blocking / "
        f"{effective_optional_gap_count} 選配。"
    )


def _status_note(status: str) -> str:
    if status == "degraded":
        return "仍有核心實作或設定缺口，需要先處理 blocking gaps。"
    if status == "ready_with_optional_gaps":
        return "核心實作已就緒；剩餘項目屬於外部部署、額度或付費資料源選配。"
    return "核心實作與已選定的外部能力都已就緒。"


def _local_auto_defaults(status: dict) -> dict:
    direct = status.get("local_dependency_auto_defaults")
    if isinstance(direct, dict):
        return direct
    local_dependencies = status.get("local_dependencies")
    if isinstance(local_dependencies, dict) and isinstance(
        local_dependencies.get("auto_defaults_preview"),
        dict,
    ):
        return local_dependencies["auto_defaults_preview"]
    return {}


def _local_auto_default_match(
    ref: OptimizationCapabilityRef,
    local_auto_defaults: dict,
) -> dict | None:
    if ref.action_type != "free_local_or_external_config":
        return None
    matches = local_auto_defaults.get("capability_matches")
    if not isinstance(matches, list):
        return None
    for match in matches:
        if not isinstance(match, dict):
            continue
        if match.get("area") == ref.area and match.get("capability") == ref.capability:
            return match
    return None


def _local_auto_defaults_summary(local_auto_defaults: dict) -> dict:
    if not local_auto_defaults:
        return {}
    return {
        "mode": local_auto_defaults.get("mode"),
        "compatible_audit_command": local_auto_defaults.get("compatible_audit_command"),
        "detected": local_auto_defaults.get("detected") or {},
        "would_apply_groups": local_auto_defaults.get("would_apply_groups") or [],
        "already_configured_groups": local_auto_defaults.get("already_configured_groups") or [],
        "local_action_available_count": int(
            local_auto_defaults.get("local_action_available_count") or 0
        ),
    }


def _no_gap_action() -> dict:
    return {
        "domain_id": None,
        "domain_label": "全部",
        "capability": None,
        "label": "無立即缺口",
        "status": "ready",
        "optional": False,
        "external": False,
        "action_type": "monitoring",
        "next_action": "目前沒有需要立即改程式的缺口；維持 audit、報告觀測與額度監控即可。",
    }


def _ratio(ready: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(ready / total, 4)
