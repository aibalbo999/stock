from __future__ import annotations

import argparse
import json
from typing import Any

from app.services.service_status import service_status


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
        "company_filing_structured_api_fallback",
        "Structured company filing API fallback",
        "Configure COMPANY_FILING_STRUCTURED_API_PROVIDER/URL/TOKEN for TEJ or another provider.",
    ),
)


def external_integration_report(status: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = status or service_status()
    matrix = snapshot.get("upgrade_capability_matrix") or {}
    checks = []
    for area, capability, label, remediation in EXTERNAL_CHECKS:
        item = ((matrix.get(area) or {}).get(capability) or {})
        checks.append(
            {
                "area": area,
                "capability": capability,
                "label": label,
                "status": item.get("status") or "unknown",
                "ready": item.get("status") == "ready",
                "evidence": item.get("evidence") or {},
                "remediation": item.get("remediation") or remediation,
            }
        )
    return {
        "status": "ready" if all(check["ready"] for check in checks) else "caution",
        "ready_count": sum(1 for check in checks if check["ready"]),
        "check_count": len(checks),
        "checks": checks,
        "local_start_command": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "strict_command": ".venv/bin/python scripts/external_integrations_smoke.py --strict --json",
    }


def format_external_integration_report(report: dict[str, Any]) -> str:
    lines = [
        f"External integrations: {report['status']} "
        f"({report['ready_count']}/{report['check_count']} ready)"
    ]
    for check in report.get("checks") or []:
        marker = "OK" if check.get("ready") else "WARN"
        lines.append(f"- [{marker}] {check['label']}: {check['status']}")
        if not check.get("ready"):
            lines.append(f"  fix: {check['remediation']}")
    lines.append(f"Local start: {report['local_start_command']}")
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
