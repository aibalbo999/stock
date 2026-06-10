from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.services.external_deployment_readiness import (
    external_deployment_enablement_profile,
    external_deployment_enablement_summary,
    external_deployment_local_projection,
    external_deployment_pending_gap_action_counts,
    external_deployment_pending_gap_rows,
)
from app.services.service_status import service_status


@dataclass(frozen=True)
class UpgradeAuditRequirement:
    area: str
    capability: str
    label: str
    status_path: tuple[str, ...]
    required_statuses: tuple[str, ...] = ("ready",)
    optional: bool = False
    remediation: str = ""


REQUIREMENTS: tuple[UpgradeAuditRequirement, ...] = (
    UpgradeAuditRequirement(
        "ai_rag",
        "multilingual_embedding",
        "明確使用繁中/多語 embedding",
        ("upgrade_capability_matrix", "ai_rag", "multilingual_embedding"),
        remediation="設定 RAG_EMBEDDING_PROVIDER / RAG_EMBEDDING_MODEL，並安裝對應 embedding 依賴或 API key。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "llm_sdk_and_fallback",
        "LLM SDK 與模型降級能力",
        ("upgrade_capability_matrix", "ai_rag", "llm_sdk_and_fallback"),
        remediation="確認 LLM_PROVIDER、fallback model、LiteLLM/google-genai 依賴與對應 API key。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "llm_quota_routing",
        "免費額度感知模型路由",
        ("upgrade_capability_matrix", "ai_rag", "llm_quota_routing"),
        remediation=(
            "確認 PRIMARY_LLM_MODEL、LLM_FALLBACK_MODELS、LLM_QUOTA_HARD_ROUTING_ENABLED、"
            "LLM_MODEL_QUOTA_COOLDOWN_SECONDS 與 LLM_MODEL_DAILY_REQUEST_BUDGETS 符合智慧優先、"
            "官方 Free Tier 參考值與 Gemma 高額度保底策略。"
        ),
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "hybrid_search",
        "Hybrid Search / BM25 關鍵字檢索",
        ("upgrade_capability_matrix", "ai_rag", "hybrid_search"),
        remediation="啟用 RAG_HYBRID_SEARCH_ENABLED，確認 BM25 tokenizer 與 retrieval trace 可用。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "reranking",
        "模型級 reranking",
        ("upgrade_capability_matrix", "ai_rag", "reranking"),
        remediation="安裝 sentence-transformers / 設定 Cohere key / 啟用 LLM reranker，避免只退回 keyword fallback。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "llm_observability",
        "LLM/RAG observability",
        ("upgrade_capability_matrix", "ai_rag", "llm_observability"),
        remediation="啟用 LLM_OBSERVABILITY_ENABLED，確認 LLM token/latency/cost trace 與 retrieval trace 可用。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "visual_rag",
        "Visual RAG / VLM 財報解析",
        ("upgrade_capability_matrix", "ai_rag", "visual_rag"),
        optional=True,
        remediation=(
            '若要解析掃描型或複雜表格 PDF，安裝 pip install -e ".[visual]"，'
            "設定 COMPANY_FILING_VISUAL_RAG_ENABLED=true，並配置 vision-capable LLM key/model。"
        ),
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "graphrag_context",
        "GraphRAG 檢索脈絡",
        ("upgrade_capability_matrix", "ai_rag", "graphrag_context"),
        remediation="確認供應鏈 graph、retrieval_plan 與 evidence policy 生成成功。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "graphrag_path_reasoning",
        "GraphRAG shortest-path 推理脈絡",
        ("upgrade_capability_matrix", "ai_rag", "graphrag_path_reasoning"),
        remediation="確認 /supply-chain/graph/reasoning 可輸出 shortest-path context、Cypher template 與 evidence policy。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "graphrag_agentic_cypher",
        "GraphRAG guarded LLM Cypher planner",
        ("upgrade_capability_matrix", "ai_rag", "graphrag_agentic_cypher"),
        remediation="確認 /supply-chain/graph/cypher-plan 可輸出 read-only、白名單 schema 驗證後的 Cypher plan。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "neo4j_payload_export",
        "Neo4j parameterized payload export",
        ("upgrade_capability_matrix", "ai_rag", "neo4j_payload_export"),
        remediation="確認 /supply-chain/graph/neo4j 可輸出 parameterized Cypher payload。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "neo4j_import",
        "外部 Neo4j 匯入連線",
        ("upgrade_capability_matrix", "ai_rag", "neo4j_import"),
        optional=True,
        remediation="若正式部署需要 live graph import，設定 NEO4J_URI / 帳密並啟動 Neo4j。",
    ),
    UpgradeAuditRequirement(
        "ai_rag",
        "graphrag_live_cypher_query",
        "GraphRAG guarded live Cypher query",
        ("upgrade_capability_matrix", "ai_rag", "graphrag_live_cypher_query"),
        optional=True,
        remediation=(
            "若正式部署需要 LLM 產生 guarded Cypher 後直接查 Neo4j，"
            "設定 NEO4J_URI / 帳密並確認 /supply-chain/graph/cypher-query 可執行 read-only 查詢。"
        ),
    ),
    UpgradeAuditRequirement(
        "architecture",
        "thin_api_controller",
        "API controller/service 分層",
        ("upgrade_capability_matrix", "architecture", "thin_api_controller"),
        remediation="main.py 應維持 thin app entry；router 組裝、舊 helper 匯出與業務相容層需留在獨立 app_factory / compatibility / service 模組。",
    ),
    UpgradeAuditRequirement(
        "architecture",
        "workflow_orchestration",
        "可恢復 workflow orchestration",
        ("upgrade_capability_matrix", "architecture", "workflow_orchestration"),
        remediation="確認 WORKFLOW_ENGINE 狀態、checkpoint store 與 local/external fallback policy。",
    ),
    UpgradeAuditRequirement(
        "architecture",
        "streamlit_mpa_background_tasks",
        "Streamlit MPA 與背景任務輪詢",
        ("upgrade_capability_matrix", "architecture", "streamlit_mpa_background_tasks"),
        remediation=(
            "確認 streamlit_app.py 使用 st.navigation/pages，CSS 已外部化，"
            "分析/補資料/補強改走 FastAPI/Celery task endpoint，且 UI source 沒有 asyncio.run 或長 POST timeout。"
        ),
    ),
    UpgradeAuditRequirement(
        "architecture",
        "background_task_queue",
        "背景任務 queue readiness",
        ("upgrade_capability_matrix", "architecture", "background_task_queue"),
        remediation=(
            "啟動 Redis/Celery，確認 app.api.task_exports 匯出 celery_app 與必要 task，"
            "並保持背景任務提交 endpoint 的 structured error boundary。"
        ),
    ),
    UpgradeAuditRequirement(
        "architecture",
        "python_runtime",
        "Python 3.11+ runtime",
        ("upgrade_capability_matrix", "architecture", "python_runtime"),
        optional=True,
        remediation="目前執行中的 Python 版本低於專案目標；請用 Python 3.11+ 重建 .venv 並重新啟動 API/Streamlit/Celery。",
    ),
    UpgradeAuditRequirement(
        "architecture",
        "database_migrations",
        "Alembic database migrations",
        ("upgrade_capability_matrix", "architecture", "database_migrations"),
        remediation="執行 alembic upgrade head 或 stamp head，並確認 DB schema 與 head revision 對齊。",
    ),
    UpgradeAuditRequirement(
        "architecture",
        "secret_scanning",
        "外部密鑰掃描工具整合",
        ("upgrade_capability_matrix", "architecture", "secret_scanning"),
        remediation="安裝 detect-secrets 或 gitleaks，並確認 scripts/security_scan.py --engine auto 可優先使用外部掃描器。",
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "market_data_cache",
        "Redis 市場/財務資料快取",
        ("upgrade_capability_matrix", "data_business_logic", "market_data_cache"),
        remediation="啟動 Redis 並確認 MARKET_DATA_CACHE_ENABLED 與 TTL 設定。",
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "market_data_provider_fallback",
        "FinMind/Fugle/官方 OpenAPI fallback",
        ("upgrade_capability_matrix", "data_business_logic", "market_data_provider_fallback"),
        remediation="設定 FinMind/Fugle 授權來源或啟用官方 OpenAPI 最新資料救援。",
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "latest_report_retention",
        "最新版報告保留策略",
        ("upgrade_capability_matrix", "data_business_logic", "latest_report_retention"),
        remediation="確認報告寫入、報告中心、品質摘要與 maintenance cleanup 都使用 latest-per-topic retention，且舊 markdown/html/pdf 報告檔會同步清理。",
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_fetch_hardening",
        "公司文件反爬蟲與 PDF/HTML 表格解析",
        ("upgrade_capability_matrix", "data_business_logic", "company_filing_fetch_hardening"),
        remediation="確認 User-Agent、重試、PDF/HTML table extraction、Browserless/FlareSolverr/ScrapingBee/BrightData/Playwright 後援設定。",
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_render_provider_contract",
        "公司文件 render/unlocker provider contract",
        (
            "upgrade_capability_matrix",
            "data_business_logic",
            "company_filing_render_provider_contract",
        ),
        remediation=(
            "執行 .venv/bin/python scripts/company_filing_render_smoke.py "
            "--provider-contract --json，確認 Browserless/FlareSolverr/ScrapingBee/"
            "BrightData request/response mapping。"
        ),
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_pdf_table_parser_runtime",
        "PDF 表格 parser runtime",
        (
            "upgrade_capability_matrix",
            "data_business_logic",
            "company_filing_pdf_table_parser_runtime",
        ),
        optional=True,
        remediation='若需要從 PDF 財報抽取表格，安裝 pip install -e ".[pdf]" 或至少安裝 pdfplumber / unstructured[pdf]。',
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_browser_or_proxy_fallback",
        "公司文件 Proxy / Browser render / Playwright 後援",
        (
            "upgrade_capability_matrix",
            "data_business_logic",
            "company_filing_browser_or_proxy_fallback",
        ),
        optional=True,
        remediation=(
            "正式部署若常遇到 MOPS/IR 入口被擋、空殼頁或動態頁，設定 COMPANY_FILING_PROXY_URLS、"
            "COMPANY_FILING_BROWSER_RENDER_PROVIDER/URL 或 COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=true。"
        ),
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_high_risk_unlocker",
        "MOPS/TWSE/TPEx 高風險文件 unlocker",
        (
            "upgrade_capability_matrix",
            "data_business_logic",
            "company_filing_high_risk_unlocker",
        ),
        optional=True,
        remediation=(
            "正式部署若要穩定抓取 MOPS、doc.twse、TWSE/TPEx 等高風險公開文件，"
            "設定 FlareSolverr、ScrapingBee 或 BrightData 這類 CAPTCHA/anti-bot unlocker；"
            "Browserless/Playwright 只算瀏覽器渲染後援。"
        ),
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_official_material_information_openapi",
        "TWSE/TPEx 官方重大訊息 OpenAPI fallback",
        (
            "upgrade_capability_matrix",
            "data_business_logic",
            "company_filing_official_material_information_openapi",
        ),
        remediation="確認公司文件 discovery 先接 TWSE/TPEx t187ap04 官方重大訊息 OpenAPI，再退回 Google News/網站搜尋。",
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_structured_api_fallback",
        "公司文件結構化 API 備援",
        (
            "upgrade_capability_matrix",
            "data_business_logic",
            "company_filing_structured_api_fallback",
        ),
        optional=True,
        remediation=(
            "若法說會簡報或重大訊息常被 MOPS/IR 擋住，設定 "
            "COMPANY_FILING_STRUCTURED_API_PROVIDER/URL/TOKEN 串接 TEJ 或專業資料 API。"
        ),
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_structured_api_sample_contract",
        "公司文件結構化 API sample contract",
        (
            "upgrade_capability_matrix",
            "data_business_logic",
            "company_filing_structured_api_sample_contract",
        ),
        remediation=(
            "執行 .venv/bin/python scripts/structured_company_filing_smoke.py "
            "--sample-json examples/structured_company_filing_sample.json "
            "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json，"
            "確認樣本 payload 可轉成 CompanyFilingDocument。"
        ),
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "company_filing_cache",
        "公司文件 URL 解析快取",
        ("upgrade_capability_matrix", "data_business_logic", "company_filing_cache"),
        remediation="啟動 Redis 並確認 COMPANY_FILING_CACHE_ENABLED。",
    ),
    UpgradeAuditRequirement(
        "data_business_logic",
        "source_quality_weighting",
        "來源可信度分層與低品質來源降權",
        ("upgrade_capability_matrix", "data_business_logic", "source_quality_weighting"),
        remediation="確認 source credibility weights 與候選升格規則仍排除論壇/投資網誌作高可信證據。",
    ),
)

EXTERNAL_INTEGRATION_CAPABILITIES = frozenset(
    {
        ("ai_rag", "neo4j_import"),
        ("ai_rag", "graphrag_live_cypher_query"),
        ("ai_rag", "visual_rag"),
        ("data_business_logic", "company_filing_pdf_table_parser_runtime"),
        ("data_business_logic", "company_filing_browser_or_proxy_fallback"),
        ("data_business_logic", "company_filing_high_risk_unlocker"),
        ("data_business_logic", "company_filing_structured_api_fallback"),
    }
)
DEPLOYMENT_CHECK_CAPABILITIES = EXTERNAL_INTEGRATION_CAPABILITIES | frozenset(
    {
        ("architecture", "python_runtime"),
    }
)


def audit_upgrade_capabilities(
    status: dict | None = None,
    *,
    strict_external: bool = False,
) -> dict:
    status = status or service_status()
    local_dependencies = (
        status.get("local_dependencies")
        if isinstance(status.get("local_dependencies"), dict)
        else {}
    )
    local_dependency_auto_defaults = (
        status.get("local_dependency_auto_defaults")
        if isinstance(status.get("local_dependency_auto_defaults"), dict)
        else local_dependencies.get("auto_defaults_preview")
        if isinstance(local_dependencies.get("auto_defaults_preview"), dict)
        else {}
    )
    checks = [
        _requirement_result(requirement, status, strict_external=strict_external)
        for requirement in REQUIREMENTS
    ]
    failures = [check for check in checks if check["severity"] == "fail"]
    all_warnings = [check for check in checks if check["severity"] == "warn"]
    optional_warnings = [
        check
        for check in all_warnings
        if _is_nonblocking_optional_deployment_warning(check, strict_external=strict_external)
    ]
    warnings = [check for check in all_warnings if check not in optional_warnings]
    implementation_checks = [check for check in checks if not check.get("deployment_check")]
    deployment_checks = [check for check in checks if check.get("deployment_check")]
    implementation = _summarize_checks(implementation_checks)
    deployment = _summarize_checks(deployment_checks)
    deployment_blocking_checks = [
        check
        for check in deployment_checks
        if not _is_nonblocking_optional_deployment_warning(
            check,
            strict_external=strict_external,
        )
    ]
    deployment_blocking = _summarize_checks(deployment_blocking_checks)
    deployment_optional_only = bool(
        deployment["status"] == "caution"
        and deployment_blocking["status"] == "ready"
        and optional_warnings
    )
    deployment.update(
        {
            "blocking_status": deployment_blocking["status"],
            "blocking_ready": deployment_blocking["ready"],
            "blocking_total_checks": deployment_blocking["total_checks"],
            "blocking_warnings": deployment_blocking["warnings"],
            "blocking_failures": deployment_blocking["failures"],
            "optional_only": deployment_optional_only,
        }
    )
    areas = defaultdict(lambda: {"ready": 0, "warnings": 0, "failures": 0, "checks": 0})
    for check in checks:
        area = areas[check["area"]]
        area["checks"] += 1
        if check["severity"] == "fail":
            area["failures"] += 1
        elif check["severity"] == "warn":
            area["warnings"] += 1
        else:
            area["ready"] += 1

    audit = {
        "overall_status": "failed" if failures else "caution" if warnings else "ready",
        "strict_external": strict_external,
        "summary": {
            "total_checks": len(checks),
            "ready": sum(1 for check in checks if check["severity"] == "pass"),
            "warnings": len(warnings),
            "optional_warnings": len(optional_warnings),
            "total_warnings": len(all_warnings),
            "failures": len(failures),
            "implementation_status": implementation["status"],
            "deployment_status": deployment["status"],
            "deployment_blocking_status": deployment_blocking["status"],
            "deployment_blocking_warnings": deployment_blocking["warnings"],
            "deployment_blocking_failures": deployment_blocking["failures"],
            "deployment_optional_only": deployment_optional_only,
        },
        "implementation": implementation,
        "deployment": deployment,
        "local_dependencies": local_dependencies,
        "local_dependency_auto_defaults": local_dependency_auto_defaults,
        "areas": dict(sorted(areas.items())),
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
        "optional_warnings": optional_warnings,
        "all_warnings": all_warnings,
    }
    audit["external_deployment_enablement"] = external_deployment_enablement_summary(
        audit,
        local_dependency_status=local_dependencies,
    )
    pending_gaps = external_deployment_pending_gap_rows(
        audit,
        local_dependency_status=local_dependencies,
    )
    audit["external_deployment_pending_gaps"] = pending_gaps
    audit["external_deployment_pending_gap_action_counts"] = (
        external_deployment_pending_gap_action_counts(pending_gaps)
    )
    audit["external_deployment_local_projection"] = external_deployment_local_projection(
        pending_gaps,
        local_dependency_auto_defaults,
    )
    return audit


def _requirement_result(
    requirement: UpgradeAuditRequirement,
    status: dict,
    *,
    strict_external: bool,
) -> dict:
    capability = _path_get(status, requirement.status_path) or {}
    actual_status = str(capability.get("status") or "missing")
    is_optional = requirement.optional and not strict_external
    passed = actual_status in requirement.required_statuses
    severity = "pass" if passed else "warn" if is_optional else "fail"
    external_integration = (
        requirement.area,
        requirement.capability,
    ) in EXTERNAL_INTEGRATION_CAPABILITIES
    deployment_check = (requirement.area, requirement.capability) in DEPLOYMENT_CHECK_CAPABILITIES
    evidence = capability.get("evidence") or {}
    result = {
        "area": requirement.area,
        "capability": requirement.capability,
        "label": requirement.label,
        "status": actual_status,
        "required_statuses": list(requirement.required_statuses),
        "optional": is_optional,
        "external_integration": external_integration,
        "deployment_check": deployment_check,
        "severity": severity,
        "detail": capability.get("detail"),
        "evidence": evidence,
        "remediation": None if passed else _remediation_for_requirement(requirement, evidence),
    }
    if external_integration:
        result["enablement_profile"] = external_deployment_enablement_profile(result)
    return result


def _remediation_for_requirement(requirement: UpgradeAuditRequirement, evidence: dict) -> str:
    if (requirement.area, requirement.capability) == ("architecture", "python_runtime"):
        return _python_runtime_remediation(evidence, requirement.remediation)
    if (requirement.area, requirement.capability) == ("architecture", "background_task_queue"):
        return _background_task_queue_remediation(evidence, requirement.remediation)
    if (requirement.area, requirement.capability) == ("ai_rag", "neo4j_import"):
        return _neo4j_import_remediation(evidence, requirement.remediation)
    if (requirement.area, requirement.capability) == ("ai_rag", "graphrag_live_cypher_query"):
        endpoint = evidence.get("endpoint") or "/supply-chain/graph/cypher-query"
        commands = [
            evidence.get("payload_dry_run_cli"),
            evidence.get("smoke_cli"),
            evidence.get("import_smoke_cli"),
        ]
        command_text = "；".join(str(command) for command in commands if command)
        if command_text:
            return (
                f"{requirement.remediation} 可先以 {endpoint} 驗證 API contract；"
                f"驗證指令：{command_text}"
            )
        return f"{requirement.remediation} 可先以 {endpoint} 或 Neo4j GraphRAG smoke 指令驗證 read-only plan。"
    if requirement.capability == "company_filing_browser_or_proxy_fallback":
        return _append_smoke_command(
            requirement.remediation,
            _first_nested_value(
                evidence,
                ("browser_render_runtime", "smoke_cli"),
                ("playwright_render_runtime", "smoke_cli"),
            ),
        )
    if requirement.capability == "company_filing_high_risk_unlocker":
        remediation = requirement.remediation
        recommended_env = [
            str(item).strip() for item in evidence.get("recommended_env", []) if str(item).strip()
        ]
        if recommended_env:
            remediation = f"{remediation} 建議 env：{'；'.join(recommended_env)}。"
        return _append_smoke_command(remediation, evidence.get("smoke_cli"))
    if requirement.capability == "company_filing_structured_api_fallback":
        return _append_smoke_commands(
            requirement.remediation,
            [
                _first_nested_value(evidence, ("runtime", "sample_contract_cli")),
                _first_nested_value(
                    evidence,
                    ("runtime", "free_validation", "local_fixture_http_smoke_cli"),
                    ("runtime", "local_fixture_http_smoke_cli"),
                    ("local_fixture_http_smoke_cli",),
                ),
                _first_nested_value(
                    evidence,
                    ("runtime", "free_validation", "local_fixture_provider_profile_smoke_cli"),
                    ("runtime", "local_fixture_provider_profile_smoke_cli"),
                    ("local_fixture_provider_profile_smoke_cli",),
                ),
                _first_nested_value(evidence, ("runtime", "local_fixture_start_cli")),
                _first_nested_value(evidence, ("runtime", "local_fixture_smoke_cli")),
                _first_nested_value(evidence, ("runtime", "smoke_cli")),
            ],
        )
    return requirement.remediation


def _is_nonblocking_optional_deployment_warning(check: dict, *, strict_external: bool) -> bool:
    return bool(
        not strict_external
        and check.get("severity") == "warn"
        and check.get("optional")
        and check.get("deployment_check")
        and check.get("external_integration")
    )


def _python_runtime_remediation(evidence: dict, default: str) -> str:
    parts = []
    install_hints = evidence.get("interpreter_install_hints") or []
    install_commands = [
        str(hint.get("command"))
        for hint in install_hints
        if isinstance(hint, dict) and str(hint.get("command") or "").strip()
    ]
    if install_commands:
        parts.append("先確認有支援 interpreter：" + " 或 ".join(install_commands[:3]))
    if evidence.get("bootstrap_dry_run_cli"):
        parts.append(f"預覽：{evidence['bootstrap_dry_run_cli']}")
    if evidence.get("bootstrap_cli"):
        parts.append(f"重建：{evidence['bootstrap_cli']}")
    if evidence.get("recommended_action"):
        parts.append(str(evidence["recommended_action"]))
    return "；".join(parts) if parts else default


def _neo4j_import_remediation(evidence: dict, default: str) -> str:
    commands = [
        evidence.get("payload_dry_run_cli"),
        evidence.get("smoke_cli"),
        evidence.get("import_smoke_cli"),
    ]
    command_text = "；".join(str(command) for command in commands if command)
    return f"{default} 驗證指令：{command_text}" if command_text else default


def _append_smoke_command(message: str, command: object) -> str:
    command_text = str(command or "").strip()
    return f"{message} 驗證指令：{command_text}" if command_text else message


def _append_smoke_commands(message: str, commands: list[object]) -> str:
    command_text = "；".join(
        str(command).strip() for command in commands if str(command or "").strip()
    )
    return f"{message} 驗證指令：{command_text}" if command_text else message


def _background_task_queue_remediation(evidence: dict, default: str) -> str:
    reasons: list[str] = []
    missing_exports = [
        str(item).strip() for item in evidence.get("missing_task_exports") or [] if str(item).strip()
    ]
    if evidence.get("submission_contract_ready") is False:
        if missing_exports:
            reasons.append("缺少 Celery task exports：" + "、".join(missing_exports))
        elif evidence.get("task_export_error"):
            reasons.append(f"task export error: {evidence['task_export_error']}")
        elif evidence.get("task_names_match_expected") is False:
            reasons.append("Celery task name 與 EXPECTED_TASK_NAMES 不一致")
        else:
            reasons.append("確認 app.api.task_exports 匯出 celery_app 與所有必要 task")
    if evidence.get("task_queue_source_diagnostics_extracted") is False:
        reasons.append("恢復 task queue source diagnostics collector")
    if evidence.get("task_async_bridge_guard_present") is False:
        reasons.append("確認 Celery task 透過 app.core.async_bridge 執行 async 呼叫")
    if evidence.get("app_asyncio_run_policy_ready") is False:
        reasons.append("移除 app/ 內未授權的 asyncio.run 呼叫")
    if evidence.get("compose_runtime_env_passthrough_ready") is False:
        reasons.append("補齊 docker-compose Celery runtime env passthrough")
    if evidence.get("structured_task_submission_errors") is False:
        reasons.append("恢復背景任務提交 endpoint 的 structured error boundary")
    if evidence.get("background_task_submission_handlers_extracted") is False and evidence.get(
        "operation_task_submission_handlers_extracted"
    ) is False:
        reasons.append("恢復背景任務提交 handler/service 抽離")
    if evidence.get("background_task_control_handlers_extracted") is False:
        reasons.append("恢復 task status/cancel/retry control handlers")
    if evidence.get("task_failure_diagnostics_shared_service") is False:
        reasons.append("恢復 task failure diagnostics shared service")
    if evidence.get("task_failure_diagnostics_persisted_to_run_payload") is False:
        reasons.append("將 task failure diagnostics 寫回 analysis run payload")
    return "；".join(reasons) + "。" if reasons else default


def _first_nested_value(payload: dict, *paths: tuple[str, ...]) -> object:
    for path in paths:
        value = _path_get(payload, path)
        if value:
            return value
    return None


def _summarize_checks(checks: list[dict]) -> dict:
    failures = sum(1 for check in checks if check["severity"] == "fail")
    warnings = sum(1 for check in checks if check["severity"] == "warn")
    ready = sum(1 for check in checks if check["severity"] == "pass")
    return {
        "status": "failed" if failures else "caution" if warnings else "ready",
        "total_checks": len(checks),
        "ready": ready,
        "warnings": warnings,
        "failures": failures,
    }


def _path_get(payload: dict, path: tuple[str, ...]) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
