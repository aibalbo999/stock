from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.service_status import service_status
from app.services.external_deployment_readiness import external_deployment_enablement_profile

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
STRUCTURED_COMPANY_FILING_SAMPLE_PATH = Path("examples/structured_company_filing_sample.json")
COMPANY_FILING_RENDER_SMOKE_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--url https://example.com/ --json"
)
HIGH_RISK_COMPANY_FILING_RENDER_SMOKE_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--url https://mops.twse.com.tw/ --json"
)
COMPANY_FILING_RENDER_PROVIDER_CONTRACT_COMMAND = (
    ".venv/bin/python scripts/company_filing_render_smoke.py "
    "--provider-contract --json"
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
        STRUCTURED_COMPANY_FILING_SMOKE_COMMAND,
    ],
}


def external_integration_report(status: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = status or service_status()
    matrix = snapshot.get("upgrade_capability_matrix") or {}
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
            "evidence": evidence,
            "smoke_commands": external_check_smoke_commands(capability, evidence),
            "remediation": item.get("remediation") or remediation,
        }
        check["enablement_profile"] = external_deployment_enablement_profile(check)
        checks.append(check)
    checks.extend(local_graphrag_contract_checks(matrix))
    checks.append(company_filing_render_provider_contract_check())
    checks.append(structured_company_filing_sample_contract_check())
    return {
        "status": "ready" if all(check["ready"] for check in checks) else "caution",
        "ready_count": sum(1 for check in checks if check["ready"]),
        "check_count": len(checks),
        "checks": checks,
        "actionable_check_count": sum(1 for check in checks if check["smoke_commands"]),
        "local_start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "neo4j_graphrag_smoke_command": NEO4J_GRAPHRAG_SMOKE_COMMAND,
        "neo4j_import_smoke_command": NEO4J_IMPORT_SMOKE_COMMAND,
        "neo4j_local_contract_smoke_command": NEO4J_LOCAL_CONTRACT_SMOKE_COMMAND,
        "neo4j_payload_dry_run_command": NEO4J_PAYLOAD_DRY_RUN_COMMAND,
        "company_filing_render_smoke_command": COMPANY_FILING_RENDER_SMOKE_COMMAND,
        "high_risk_company_filing_render_smoke_command": HIGH_RISK_COMPANY_FILING_RENDER_SMOKE_COMMAND,
        "company_filing_render_provider_contract_command": COMPANY_FILING_RENDER_PROVIDER_CONTRACT_COMMAND,
        "structured_company_filing_smoke_command": STRUCTURED_COMPANY_FILING_SMOKE_COMMAND,
        "structured_company_filing_sample_command": STRUCTURED_COMPANY_FILING_SAMPLE_COMMAND,
        "structured_company_filing_sample_status": checks[-1]["status"],
        "strict_command": ".venv/bin/python scripts/external_integrations_smoke.py --strict --json",
    }


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


def external_check_smoke_commands(capability: str, evidence: dict[str, Any]) -> list[str]:
    commands = _commands_from_payload(evidence)
    commands = _commands_for_capability(capability, commands)
    preferred_order = DEFAULT_SMOKE_COMMANDS_BY_CAPABILITY.get(capability, [])
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
    lines.append(f"Structured filing smoke: {report['structured_company_filing_smoke_command']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-check optional external deployment integrations."
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero unless all checks are ready.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = external_integration_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_external_integration_report(report))
    return 1 if args.strict and report["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
