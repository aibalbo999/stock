from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.external_deployment_readiness import (
    external_deployment_enablement_profile,
    external_deployment_enablement_summary,
    external_deployment_local_projection,
    external_deployment_pending_gap_action_counts,
    external_deployment_pending_gap_rows,
)
from app.services.service_status import service_status

try:
    from scripts.neo4j_graphrag_smoke import apply_local_neo4j_defaults
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from neo4j_graphrag_smoke import apply_local_neo4j_defaults

try:
    from scripts.upgrade_audit import (
        LOCAL_BROWSERLESS_PORT,
        LOCAL_FLARESOLVERR_PORT,
        apply_local_browser_render_env_defaults,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from upgrade_audit import (
        LOCAL_BROWSERLESS_PORT,
        LOCAL_FLARESOLVERR_PORT,
        apply_local_browser_render_env_defaults,
    )

try:
    from scripts.company_filing_render_smoke import (
        company_filing_render_provider_contract_report,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from company_filing_render_smoke import company_filing_render_provider_contract_report

try:
    from scripts.structured_company_filing_smoke import (
        structured_company_filing_sample_report,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from structured_company_filing_smoke import structured_company_filing_sample_report


NEO4J_GRAPHRAG_SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
)
NEO4J_IMPORT_SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json"
)
NEO4J_LOCAL_DEFAULTS_GRAPHRAG_SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--local-neo4j-defaults --tickers 2330 --target-ticker 2382 "
    "--question 上下游衝擊 --json"
)
NEO4J_LOCAL_DEFAULTS_IMPORT_SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--local-neo4j-defaults --tickers 2330 --target-ticker 2382 "
    "--question 上下游衝擊 --import-first --json"
)
NEO4J_LOCAL_CONTRACT_SMOKE_COMMAND = (
    ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
    "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --local-contract --json"
)
NEO4J_PAYLOAD_DRY_RUN_COMMAND = (
    ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run"
)
STRUCTURED_COMPANY_FILING_SMOKE_COMMAND = (
    ".venv/bin/python scripts/structured_company_filing_smoke.py "
    "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
)
STRUCTURED_COMPANY_FILING_SAMPLE_COMMAND = (
    ".venv/bin/python scripts/structured_company_filing_smoke.py "
    "--sample-json examples/structured_company_filing_sample.json "
    "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
)
STRUCTURED_COMPANY_FILING_LOCAL_FIXTURE_START_COMMAND = (
    ".venv/bin/python scripts/local_structured_company_filing_api.py "
    "--sample-json examples/structured_company_filing_sample.json "
    "--host 127.0.0.1 --port 8794"
)
STRUCTURED_COMPANY_FILING_LOCAL_FIXTURE_SMOKE_COMMAND = (
    "COMPANY_FILING_STRUCTURED_API_PROVIDER=custom "
    "COMPANY_FILING_STRUCTURED_API_URL=http://127.0.0.1:8794/filings "
    ".venv/bin/python scripts/structured_company_filing_smoke.py "
    "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
)
STRUCTURED_COMPANY_FILING_LOCAL_PROVIDER_PROFILE_SMOKE_COMMAND = (
    ".venv/bin/python scripts/structured_company_filing_fixture_smoke.py "
    "--provider-profile tej --json --strict"
)
STRUCTURED_COMPANY_FILING_SAMPLE_PATH = Path("examples/structured_company_filing_sample.json")
COMPANY_FILING_RENDER_SMOKE_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--url https://example.com/ --json"
)
HIGH_RISK_COMPANY_FILING_RENDER_SMOKE_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--local-browser-render-defaults --prefer-unlocker "
    "--url https://mops.twse.com.tw/ --json"
)
COMPANY_FILING_RENDER_PROVIDER_CONTRACT_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--provider-contract --json"
)
EXTERNAL_LOCAL_NEO4J_SMOKE_COMMAND = (
    ".venv/bin/python scripts/external_integrations_smoke.py "
    "--local-neo4j-defaults --json"
)
EXTERNAL_LOCAL_NEO4J_WAIT_SMOKE_COMMAND = (
    ".venv/bin/python scripts/external_integrations_smoke.py "
    "--local-neo4j-defaults --wait-local-neo4j 20 --json"
)
EXTERNAL_LOCAL_BROWSER_RENDER_SMOKE_COMMAND = (
    ".venv/bin/python scripts/external_integrations_smoke.py "
    "--local-browser-render-defaults --wait-local-browserless 20 --json"
)
EXTERNAL_LOCAL_UNLOCKER_SMOKE_COMMAND = (
    ".venv/bin/python scripts/external_integrations_smoke.py "
    "--local-browser-render-defaults --prefer-unlocker "
    "--wait-local-flaresolverr 20 --json"
)

EXTERNAL_CHECKS = (
    (
        "ai_rag",
        "neo4j_import",
        "Neo4j live import",
        "Set NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD and start Neo4j.",
    ),
    (
        "ai_rag",
        "graphrag_live_cypher_query",
        "GraphRAG live read-only Cypher query",
        "Start Neo4j and keep /supply-chain/graph/cypher-query on guarded plans.",
    ),
    (
        "data_business_logic",
        "company_filing_browser_or_proxy_fallback",
        "Company filing browser/proxy render fallback",
        "Enable Browserless, Playwright, FlareSolverr, ScrapingBee, BrightData, or proxy URLs.",
    ),
    (
        "data_business_logic",
        "company_filing_high_risk_unlocker",
        "MOPS/TWSE/TPEx high-risk filing unlocker",
        "Enable FlareSolverr, ScrapingBee, or BrightData for CAPTCHA/anti-bot filing sources.",
    ),
    (
        "data_business_logic",
        "company_filing_structured_api_fallback",
        "Structured company filing API fallback",
        "Configure COMPANY_FILING_STRUCTURED_API_PROVIDER/URL/TOKEN for TEJ or another provider.",
    ),
)
SMOKE_COMMAND_KEYS = frozenset(
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
DEFAULT_SMOKE_COMMANDS_BY_CAPABILITY = {
    "neo4j_import": [
        NEO4J_PAYLOAD_DRY_RUN_COMMAND,
        NEO4J_GRAPHRAG_SMOKE_COMMAND,
        NEO4J_IMPORT_SMOKE_COMMAND,
    ],
    "neo4j_payload_export_contract": [NEO4J_PAYLOAD_DRY_RUN_COMMAND],
    "graphrag_local_cypher_dry_run": [NEO4J_LOCAL_CONTRACT_SMOKE_COMMAND],
    "graphrag_live_cypher_query": [
        NEO4J_PAYLOAD_DRY_RUN_COMMAND,
        NEO4J_LOCAL_CONTRACT_SMOKE_COMMAND,
        NEO4J_GRAPHRAG_SMOKE_COMMAND,
        NEO4J_IMPORT_SMOKE_COMMAND,
    ],
    "company_filing_render_provider_contract": [
        COMPANY_FILING_RENDER_PROVIDER_CONTRACT_COMMAND
    ],
    "company_filing_browser_or_proxy_fallback": [COMPANY_FILING_RENDER_SMOKE_COMMAND],
    "company_filing_high_risk_unlocker": [HIGH_RISK_COMPANY_FILING_RENDER_SMOKE_COMMAND],
    "company_filing_structured_api_fallback": [
        STRUCTURED_COMPANY_FILING_SAMPLE_COMMAND,
        STRUCTURED_COMPANY_FILING_LOCAL_PROVIDER_PROFILE_SMOKE_COMMAND,
        STRUCTURED_COMPANY_FILING_LOCAL_FIXTURE_SMOKE_COMMAND,
        STRUCTURED_COMPANY_FILING_SMOKE_COMMAND,
    ],
}
LOCAL_NEO4J_SMOKE_COMMANDS_BY_CAPABILITY = {
    "neo4j_import": [
        NEO4J_PAYLOAD_DRY_RUN_COMMAND,
        NEO4J_LOCAL_DEFAULTS_GRAPHRAG_SMOKE_COMMAND,
        NEO4J_LOCAL_DEFAULTS_IMPORT_SMOKE_COMMAND,
    ],
    "graphrag_live_cypher_query": [
        NEO4J_PAYLOAD_DRY_RUN_COMMAND,
        NEO4J_LOCAL_CONTRACT_SMOKE_COMMAND,
        NEO4J_LOCAL_DEFAULTS_GRAPHRAG_SMOKE_COMMAND,
        NEO4J_LOCAL_DEFAULTS_IMPORT_SMOKE_COMMAND,
    ],
}


def external_integration_report(
    status: dict[str, Any] | None = None,
    *,
    local_neo4j_defaults: dict[str, Any] | None = None,
    local_browser_render_defaults: dict[str, Any] | None = None,
    local_dependency_wait: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = status or service_status()
    matrix = snapshot.get("upgrade_capability_matrix") or {}
    use_local_neo4j_defaults = bool(
        local_neo4j_defaults and local_neo4j_defaults.get("requested")
    )
    checks = []
    for area, capability, label, remediation in EXTERNAL_CHECKS:
        item = ((matrix.get(area) or {}).get(capability) or {})
        evidence = item.get("evidence") or {}
        check = {
            "area": area,
            "capability": capability,
            "label": label,
            "status": item.get("status") or "unknown",
            "ready": item.get("status") == "ready",
            "severity": "pass" if item.get("status") == "ready" else "warn",
            "optional": True,
            "external_integration": True,
            "deployment_check": True,
            "evidence": evidence,
            "smoke_commands": external_check_smoke_commands(
                capability,
                evidence,
                local_neo4j_defaults=use_local_neo4j_defaults,
            ),
            "remediation": item.get("remediation") or remediation,
        }
        check["enablement_profile"] = external_deployment_enablement_profile(check)
        checks.append(check)
    checks.extend(local_graphrag_contract_checks(matrix))
    checks.append(company_filing_render_provider_contract_check())
    checks.append(structured_company_filing_sample_contract_check())
    local_dependency_status = (
        snapshot.get("local_dependencies")
        if isinstance(snapshot.get("local_dependencies"), dict)
        else {}
    )
    pending_gap_rows = external_deployment_pending_gap_rows(
        {"checks": checks},
        local_dependency_status=local_dependency_status,
    )
    local_dependency_auto_defaults = _local_dependency_auto_defaults(snapshot)
    report = {
        "status": "ready" if all(check["ready"] for check in checks) else "caution",
        "ready_count": sum(1 for check in checks if check["ready"]),
        "check_count": len(checks),
        "checks": checks,
        "enablement_summary": external_deployment_enablement_summary(
            {"checks": checks},
            local_dependency_status=local_dependency_status,
        ),
        "pending_gap_rows": pending_gap_rows,
        "pending_gap_action_counts": external_deployment_pending_gap_action_counts(
            pending_gap_rows
        ),
        "local_projection": external_deployment_local_projection(
            pending_gap_rows,
            local_dependency_auto_defaults,
        ),
        "actionable_check_count": sum(1 for check in checks if check["smoke_commands"]),
        "local_start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "neo4j_graphrag_smoke_command": (
            NEO4J_LOCAL_DEFAULTS_GRAPHRAG_SMOKE_COMMAND
            if use_local_neo4j_defaults
            else NEO4J_GRAPHRAG_SMOKE_COMMAND
        ),
        "neo4j_import_smoke_command": (
            NEO4J_LOCAL_DEFAULTS_IMPORT_SMOKE_COMMAND
            if use_local_neo4j_defaults
            else NEO4J_IMPORT_SMOKE_COMMAND
        ),
        "neo4j_standard_graphrag_smoke_command": NEO4J_GRAPHRAG_SMOKE_COMMAND,
        "neo4j_standard_import_smoke_command": NEO4J_IMPORT_SMOKE_COMMAND,
        "neo4j_local_defaults_graphrag_smoke_command": NEO4J_LOCAL_DEFAULTS_GRAPHRAG_SMOKE_COMMAND,
        "neo4j_local_defaults_import_smoke_command": NEO4J_LOCAL_DEFAULTS_IMPORT_SMOKE_COMMAND,
        "neo4j_local_contract_smoke_command": NEO4J_LOCAL_CONTRACT_SMOKE_COMMAND,
        "neo4j_payload_dry_run_command": NEO4J_PAYLOAD_DRY_RUN_COMMAND,
        "company_filing_render_smoke_command": COMPANY_FILING_RENDER_SMOKE_COMMAND,
        "high_risk_company_filing_render_smoke_command": HIGH_RISK_COMPANY_FILING_RENDER_SMOKE_COMMAND,
        "company_filing_render_provider_contract_command": COMPANY_FILING_RENDER_PROVIDER_CONTRACT_COMMAND,
        "structured_company_filing_smoke_command": STRUCTURED_COMPANY_FILING_SMOKE_COMMAND,
        "structured_company_filing_sample_command": STRUCTURED_COMPANY_FILING_SAMPLE_COMMAND,
        "structured_company_filing_local_fixture_start_command": (
            STRUCTURED_COMPANY_FILING_LOCAL_FIXTURE_START_COMMAND
        ),
        "structured_company_filing_local_fixture_smoke_command": (
            STRUCTURED_COMPANY_FILING_LOCAL_FIXTURE_SMOKE_COMMAND
        ),
        "structured_company_filing_local_provider_profile_smoke_command": (
            STRUCTURED_COMPANY_FILING_LOCAL_PROVIDER_PROFILE_SMOKE_COMMAND
        ),
        "structured_company_filing_sample_status": checks[-1]["status"],
        "strict_command": ".venv/bin/python scripts/external_integrations_smoke.py --strict --json",
        "local_neo4j_smoke_command": EXTERNAL_LOCAL_NEO4J_SMOKE_COMMAND,
        "local_neo4j_wait_smoke_command": EXTERNAL_LOCAL_NEO4J_WAIT_SMOKE_COMMAND,
        "local_browser_render_smoke_command": EXTERNAL_LOCAL_BROWSER_RENDER_SMOKE_COMMAND,
        "local_unlocker_smoke_command": EXTERNAL_LOCAL_UNLOCKER_SMOKE_COMMAND,
    }
    if local_neo4j_defaults:
        report["local_neo4j_defaults"] = local_neo4j_defaults
    if local_browser_render_defaults:
        report["local_browser_render_defaults"] = local_browser_render_defaults
    if local_dependency_wait:
        report["local_dependency_wait"] = local_dependency_wait
    return report


def _local_dependency_auto_defaults(snapshot: dict[str, Any]) -> dict[str, Any]:
    auto_defaults = snapshot.get("local_dependency_auto_defaults")
    if isinstance(auto_defaults, dict):
        return auto_defaults
    local_dependencies = snapshot.get("local_dependencies")
    if isinstance(local_dependencies, dict) and isinstance(
        local_dependencies.get("auto_defaults_preview"),
        dict,
    ):
        return local_dependencies["auto_defaults_preview"]
    return {}


def company_filing_render_provider_contract_check() -> dict[str, Any]:
    report = company_filing_render_provider_contract_report()
    return {
        "area": "data_business_logic",
        "capability": "company_filing_render_provider_contract",
        "label": "Company filing render provider contract",
        "status": report.get("status") or "unknown",
        "ready": bool(report.get("ready")),
        "evidence": report,
        "smoke_commands": [COMPANY_FILING_RENDER_PROVIDER_CONTRACT_COMMAND],
        "remediation": report.get("remediation")
        or "Keep Browserless/FlareSolverr/ScrapingBee/BrightData request and response mappings healthy.",
    }


def local_graphrag_contract_checks(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    ai_rag = matrix.get("ai_rag") if isinstance(matrix.get("ai_rag"), dict) else {}
    payload_item = (
        ai_rag.get("neo4j_payload_export")
        if isinstance(ai_rag.get("neo4j_payload_export"), dict)
        else {}
    )
    cypher_item = (
        ai_rag.get("graphrag_agentic_cypher")
        if isinstance(ai_rag.get("graphrag_agentic_cypher"), dict)
        else {}
    )
    return [
        neo4j_payload_export_contract_check(payload_item),
        graphrag_local_cypher_dry_run_check(cypher_item),
    ]


def neo4j_payload_export_contract_check(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    ready = bool(item.get("status") == "ready" or evidence.get("payload_export_ready"))
    status = "ready" if ready else str(item.get("status") or "unknown")
    return {
        "area": "ai_rag",
        "capability": "neo4j_payload_export_contract",
        "label": "Neo4j payload local contract",
        "status": status,
        "ready": ready,
        "evidence": {
            "capability_status": item.get("status"),
            **evidence,
        },
        "smoke_commands": [NEO4J_PAYLOAD_DRY_RUN_COMMAND],
        "remediation": item.get("remediation")
        or "Keep /supply-chain/graph/neo4j producing parameterized neo4j_cypher_v1 payloads.",
    }


def graphrag_local_cypher_dry_run_check(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    plan = (
        evidence.get("agentic_cypher_plan_example")
        if isinstance(evidence.get("agentic_cypher_plan_example"), dict)
        else {}
    )
    validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
    ready = bool(
        item.get("status") == "ready"
        and evidence.get("local_dry_run_enabled")
        and evidence.get("local_dry_run_status") == "executed_dry_run"
        and validation.get("valid")
        and validation.get("read_only")
    )
    status = "ready" if ready else str(item.get("status") or "unknown")
    return {
        "area": "ai_rag",
        "capability": "graphrag_local_cypher_dry_run",
        "label": "GraphRAG local guarded Cypher dry-run",
        "status": status,
        "ready": ready,
        "evidence": {
            "capability_status": item.get("status"),
            **evidence,
        },
        "smoke_commands": [NEO4J_LOCAL_CONTRACT_SMOKE_COMMAND],
        "remediation": item.get("remediation")
        or "Keep GraphRAG guarded Cypher planning and in-memory dry-run validation healthy.",
    }


def structured_company_filing_sample_contract_check() -> dict[str, Any]:
    report = structured_company_filing_sample_report(
        sample_json_path=_project_root() / STRUCTURED_COMPANY_FILING_SAMPLE_PATH,
        ticker="2330",
        company_name="台積電",
        document_types=("investor_presentation",),
    )
    return {
        "area": "data_business_logic",
        "capability": "company_filing_structured_api_sample_contract",
        "label": "Structured company filing sample contract",
        "status": report.get("status") or "unknown",
        "ready": bool(report.get("ready")),
        "evidence": report,
        "smoke_commands": [STRUCTURED_COMPANY_FILING_SAMPLE_COMMAND],
        "remediation": report.get("remediation")
        or "Keep examples/structured_company_filing_sample.json convertible to CompanyFilingDocument rows.",
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def external_check_smoke_commands(
    capability: str,
    evidence: dict[str, Any],
    *,
    local_neo4j_defaults: bool = False,
) -> list[str]:
    commands = _commands_from_payload(evidence)
    commands = _commands_for_capability(capability, commands)
    if local_neo4j_defaults:
        commands = _localize_neo4j_smoke_commands(capability, commands)
    preferred_order = (
        LOCAL_NEO4J_SMOKE_COMMANDS_BY_CAPABILITY.get(capability)
        if local_neo4j_defaults
        else None
    ) or DEFAULT_SMOKE_COMMANDS_BY_CAPABILITY.get(capability, [])
    if not commands:
        commands = preferred_order
    elif preferred_order:
        commands = _order_commands(commands, preferred_order)
    deduped: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped


def _localize_neo4j_smoke_commands(capability: str, commands: list[str]) -> list[str]:
    if capability not in {"neo4j_import", "graphrag_live_cypher_query"}:
        return commands
    return [_with_local_neo4j_defaults(command) for command in commands]


def _with_local_neo4j_defaults(command: str) -> str:
    if "scripts/neo4j_graphrag_smoke.py" not in command:
        return command
    if "--local-neo4j-defaults" in command:
        return command
    script = "scripts/neo4j_graphrag_smoke.py"
    return command.replace(script, f"{script} --local-neo4j-defaults", 1)


def _commands_for_capability(capability: str, commands: list[str]) -> list[str]:
    if capability == "company_filing_browser_or_proxy_fallback":
        return [
            command
            for command in commands
            if "https://mops.twse.com.tw/" not in command
        ]
    if capability == "company_filing_high_risk_unlocker":
        high_risk_commands = [
            command
            for command in commands
            if "https://mops.twse.com.tw/" in command
        ]
        return high_risk_commands or commands
    return commands


def _order_commands(commands: list[str], preferred_order: list[str]) -> list[str]:
    ordered: list[str] = []
    remaining = list(commands)
    for preferred in preferred_order:
        for command in list(remaining):
            if command == preferred:
                ordered.append(command)
                remaining.remove(command)
                break
    ordered.extend(remaining)
    return ordered


def _commands_from_payload(payload: Any) -> list[str]:
    commands: list[str] = []
    _collect_commands(payload, commands)
    return commands


def _collect_commands(payload: Any, commands: list[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            if (
                key_text in SMOKE_COMMAND_KEYS
                or key_text.endswith("_smoke_cli")
                or key_text.endswith("_smoke_command")
            ):
                _append_command(value, commands)
            else:
                _collect_commands(value, commands)
    elif isinstance(payload, list):
        for value in payload:
            _collect_commands(value, commands)


def _append_command(value: Any, commands: list[str]) -> None:
    if isinstance(value, str):
        command = value.strip()
        if command:
            commands.append(command)
        return
    if isinstance(value, list):
        for item in value:
            _append_command(item, commands)
        return
    if isinstance(value, dict):
        _collect_commands(value, commands)


def format_external_integration_report(report: dict[str, Any]) -> str:
    lines = [
        f"External integrations: {report['status']} "
        f"({report['ready_count']}/{report['check_count']} ready)"
    ]
    enablement_summary = (
        report.get("enablement_summary")
        if isinstance(report.get("enablement_summary"), dict)
        else {}
    )
    if enablement_summary.get("total"):
        lines.append(
            "Enablement summary: "
            f"pending={int(enablement_summary.get('pending') or 0)}; "
            f"free_local={int(enablement_summary.get('free_local_pending') or 0)}; "
            f"local_action={int(enablement_summary.get('local_action_available') or 0)}; "
            f"quota_or_external={int(enablement_summary.get('quota_or_external_pending') or 0)}; "
            f"paid_external={int(enablement_summary.get('paid_external_pending') or 0)}"
        )
        if enablement_summary.get("primary_next_action"):
            lines.append(
                "Next action: " + str(enablement_summary["primary_next_action"])
            )
    pending_gap_counts = (
        report.get("pending_gap_action_counts")
        if isinstance(report.get("pending_gap_action_counts"), dict)
        else {}
    )
    if pending_gap_counts:
        lines.append(
            "Pending gap actions: "
            f"local_action={int(pending_gap_counts.get('local_action') or 0)}; "
            f"quota_or_external={int(pending_gap_counts.get('quota_or_external') or 0)}; "
            f"paid_external={int(pending_gap_counts.get('paid_external') or 0)}; "
            f"manual_configuration={int(pending_gap_counts.get('manual_configuration') or 0)}"
        )
    local_projection = (
        report.get("local_projection")
        if isinstance(report.get("local_projection"), dict)
        else {}
    )
    if local_projection:
        lines.append(
            "Effective gaps: "
            f"pending={int(local_projection.get('current_pending') or 0)} -> "
            f"{int(local_projection.get('remaining_pending') or 0)} "
            "after available local defaults; "
            f"blocking={int(local_projection.get('remaining_blocking_pending') or 0)}; "
            f"optional={int(local_projection.get('remaining_optional_pending') or 0)}; "
            f"paid_external={int(local_projection.get('remaining_paid_external_pending') or 0)}; "
            f"local_defaults={int(local_projection.get('available_local_default_gap_count') or 0)}"
        )
        if local_projection.get("next_action"):
            lines.append("Effective next action: " + str(local_projection["next_action"]))
    local_neo4j_defaults = (
        report.get("local_neo4j_defaults")
        if isinstance(report.get("local_neo4j_defaults"), dict)
        else {}
    )
    if local_neo4j_defaults:
        applied_keys = [
            str(key) for key in local_neo4j_defaults.get("applied_env_keys") or []
        ]
        applied_text = ", ".join(applied_keys) if applied_keys else "none; existing env used"
        lines.append(
            "Local Neo4j defaults: applied "
            + applied_text
            + " (current process only)"
        )
    browser_defaults = (
        report.get("local_browser_render_defaults")
        if isinstance(report.get("local_browser_render_defaults"), dict)
        else {}
    )
    if browser_defaults:
        applied_keys = [str(key) for key in browser_defaults.get("applied_env_keys") or []]
        applied_text = ", ".join(applied_keys) if applied_keys else str(
            browser_defaults.get("reason") or "none; existing env used"
        )
        lines.append(
            "Local browser render defaults: "
            + ("applied " if applied_keys else "")
            + applied_text
        )
    local_wait = (
        report.get("local_dependency_wait")
        if isinstance(report.get("local_dependency_wait"), dict)
        else {}
    )
    if "neo4j" in local_wait:
        lines.append(
            f"Local Neo4j wait: {'ready' if local_wait.get('neo4j') else 'not ready'} "
            f"within {local_wait.get('neo4j_timeout_seconds')}s"
        )
    if "browserless" in local_wait:
        lines.append(
            f"Local Browserless wait: {'ready' if local_wait.get('browserless') else 'not ready'} "
            f"within {local_wait.get('browserless_timeout_seconds')}s"
        )
    if "flaresolverr" in local_wait:
        lines.append(
            f"Local FlareSolverr wait: {'ready' if local_wait.get('flaresolverr') else 'not ready'} "
            f"within {local_wait.get('flaresolverr_timeout_seconds')}s"
        )
    for check in report.get("checks") or []:
        marker = "OK" if check.get("ready") else "WARN"
        lines.append(f"- [{marker}] {check['label']}: {check['status']}")
        enablement = (
            check.get("enablement_profile")
            if isinstance(check.get("enablement_profile"), dict)
            else {}
        )
        if enablement:
            lines.append(
                "  enablement: "
                f"{enablement.get('group_label')}; cost: {enablement.get('cost_label')}"
            )
        if not check.get("ready"):
            lines.append(f"  fix: {check['remediation']}")
            gap_row = _pending_gap_row_for_check(report, check)
            if gap_row:
                lines.append(
                    "  action: "
                    f"{gap_row.get('action_type')} "
                    f"({gap_row.get('decision')}; {gap_row.get('local_action_state')})"
                )
                local_command = str(gap_row.get("local_action_command") or "-")
                if local_command != "-":
                    lines.append(f"  command: {local_command}")
        smoke_commands = [
            str(command)
            for command in check.get("smoke_commands") or []
            if str(command).strip()
        ]
        if smoke_commands:
            lines.append("  smoke:")
            lines.extend(f"    - {command}" for command in smoke_commands)
    lines.append(f"Local start: {report['local_start_command']}")
    lines.append(f"Neo4j GraphRAG smoke: {report['neo4j_graphrag_smoke_command']}")
    lines.append(f"Neo4j local contract: {report['neo4j_local_contract_smoke_command']}")
    lines.append(f"Filing render smoke: {report['company_filing_render_smoke_command']}")
    lines.append(
        "Filing render provider contract: "
        f"{report['company_filing_render_provider_contract_command']}"
    )
    lines.append(
        f"High-risk filing unlocker smoke: {report['high_risk_company_filing_render_smoke_command']}"
    )
    lines.append(f"Structured filing sample: {report['structured_company_filing_sample_command']}")
    lines.append(
        "Structured filing provider-profile fixture: "
        f"{report['structured_company_filing_local_provider_profile_smoke_command']}"
    )
    lines.append(f"Structured filing smoke: {report['structured_company_filing_smoke_command']}")
    return "\n".join(lines)


def _pending_gap_row_for_check(report: dict[str, Any], check: dict[str, Any]) -> dict[str, Any]:
    capability = str(check.get("capability") or "")
    for row in report.get("pending_gap_rows") or []:
        if isinstance(row, dict) and row.get("capability") == capability:
            return row
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-check optional external deployment integrations."
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero unless all checks are ready.")
    parser.add_argument(
        "--local-neo4j-defaults",
        action="store_true",
        help=(
            "Apply docker-compose local Neo4j defaults for this smoke process "
            "without editing .env."
        ),
    )
    parser.add_argument(
        "--wait-local-neo4j",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait for localhost Neo4j port before checking local Neo4j status.",
    )
    parser.add_argument(
        "--local-browser-render-defaults",
        action="store_true",
        help=(
            "Apply local Browserless/FlareSolverr/Playwright render defaults for this "
            "smoke process without editing .env."
        ),
    )
    parser.add_argument(
        "--prefer-unlocker",
        action="store_true",
        help="Prefer local FlareSolverr over Browserless when applying render defaults.",
    )
    parser.add_argument(
        "--wait-local-browserless",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait for localhost Browserless port before checking render fallback status.",
    )
    parser.add_argument(
        "--wait-local-flaresolverr",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait for localhost FlareSolverr port before checking high-risk unlocker status.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    local_defaults_report = None
    if args.local_neo4j_defaults:
        applied_defaults = apply_local_neo4j_defaults()
        clear_settings_cache()
        local_defaults_report = {
            "requested": True,
            "applied_env_keys": sorted(applied_defaults),
            "note": "Defaults apply only to this smoke process; .env is unchanged.",
        }

    wait_report = {}
    if int(args.wait_local_neo4j or 0) > 0:
        wait_report["neo4j"] = wait_for_port(
            "127.0.0.1",
            7687,
            timeout_seconds=int(args.wait_local_neo4j),
        )
        wait_report["neo4j_timeout_seconds"] = int(args.wait_local_neo4j)
    browserless_wait_ready = None
    if int(args.wait_local_browserless or 0) > 0:
        browserless_wait_ready = wait_for_port(
            "127.0.0.1",
            LOCAL_BROWSERLESS_PORT,
            timeout_seconds=int(args.wait_local_browserless),
        )
        wait_report["browserless"] = browserless_wait_ready
        wait_report["browserless_timeout_seconds"] = int(args.wait_local_browserless)
    flaresolverr_wait_ready = None
    if int(args.wait_local_flaresolverr or 0) > 0:
        flaresolverr_wait_ready = wait_for_port(
            "127.0.0.1",
            LOCAL_FLARESOLVERR_PORT,
            timeout_seconds=int(args.wait_local_flaresolverr),
        )
        wait_report["flaresolverr"] = flaresolverr_wait_ready
        wait_report["flaresolverr_timeout_seconds"] = int(args.wait_local_flaresolverr)

    browser_defaults_report = None
    if args.local_browser_render_defaults:
        browserless_port_available = bool(browserless_wait_ready) or is_port_open(
            "127.0.0.1",
            LOCAL_BROWSERLESS_PORT,
        )
        flaresolverr_port_available = bool(flaresolverr_wait_ready) or is_port_open(
            "127.0.0.1",
            LOCAL_FLARESOLVERR_PORT,
        )
        browser_defaults = apply_local_browser_render_env_defaults(
            prefer_browserless=bool(browserless_wait_ready),
            prefer_unlocker=bool(args.prefer_unlocker and flaresolverr_port_available),
        )
        clear_settings_cache()
        browser_defaults_report = {
            "requested": True,
            "preferred_unlocker": bool(args.prefer_unlocker),
            "browserless_port_available": browserless_port_available,
            "flaresolverr_port_available": flaresolverr_port_available,
            "applied_env_keys": sorted(browser_defaults),
            "note": "Defaults apply only to this smoke process; .env is unchanged.",
            "reason": None
            if browser_defaults
            else (
                "flaresolverr_or_browserless_port_or_playwright_dependency_missing_"
                "or_existing_render_fallback_configured"
            ),
        }

    report = external_integration_report(
        local_neo4j_defaults=local_defaults_report,
        local_browser_render_defaults=browser_defaults_report,
        local_dependency_wait=wait_report or None,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_external_integration_report(report))
    return 1 if args.strict and report["status"] != "ready" else 0


def wait_for_port(host: str, port: int, timeout_seconds: int) -> bool:
    deadline = time.time() + max(0, timeout_seconds)
    while time.time() < deadline:
        if is_port_open(host, port):
            return True
        time.sleep(0.5)
    return is_port_open(host, port)


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def clear_settings_cache() -> None:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


if __name__ == "__main__":
    raise SystemExit(main())
