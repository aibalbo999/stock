from __future__ import annotations

import argparse
import json
import os
import socket
import time

from app.core.config import get_settings
from app.data_sources.company_filings import company_filing_playwright_browser_status
from app.services.local_dependency_diagnostics import local_docker_image_status
from app.services.supply_chain_graph_neo4j import LOCAL_NEO4J_ENV_DEFAULTS
from app.services.upgrade_audit import audit_upgrade_capabilities

LOCAL_BROWSERLESS_PORT = 3000
LOCAL_FLARESOLVERR_PORT = 8191
LOCAL_BROWSER_RENDER_ENV_DEFAULTS = {
    "COMPANY_FILING_BROWSER_RENDER_ENABLED": "true",
    "COMPANY_FILING_BROWSER_RENDER_URL": (
        f"http://127.0.0.1:{LOCAL_BROWSERLESS_PORT}/content?token=stock_ai_browserless_token"
    ),
}
LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS = {
    "COMPANY_FILING_BROWSER_RENDER_ENABLED": "true",
    "COMPANY_FILING_BROWSER_RENDER_PROVIDER": "flaresolverr",
    "COMPANY_FILING_BROWSER_RENDER_URL": f"http://127.0.0.1:{LOCAL_FLARESOLVERR_PORT}/v1",
}
LOCAL_FLARESOLVERR_IMAGE = "ghcr.io/flaresolverr/flaresolverr:latest"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit system readiness against the upgrade objective.")
    parser.add_argument(
        "--strict-external",
        action="store_true",
        help="Treat optional external integrations such as live Neo4j import as required.",
    )
    parser.add_argument(
        "--local-neo4j-defaults",
        action="store_true",
        help="Apply local docker-compose Neo4j defaults for this audit process without editing .env.",
    )
    parser.add_argument(
        "--local-browser-render-defaults",
        action="store_true",
        help=(
            "Enable local Browserless filing render fallback when the port is reachable; "
            "otherwise use local Playwright only when its browser runtime is installed."
        ),
    )
    parser.add_argument(
        "--prefer-unlocker",
        action="store_true",
        help="Prefer local FlareSolverr over Browserless when applying local browser render defaults.",
    )
    parser.add_argument(
        "--wait-local-neo4j",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait for localhost Neo4j port before auditing when local Neo4j settings are active.",
    )
    parser.add_argument(
        "--wait-local-browserless",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait for localhost Browserless port before applying local browser render defaults.",
    )
    parser.add_argument(
        "--wait-local-flaresolverr",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait for localhost FlareSolverr port before applying local browser render defaults.",
    )
    parser.add_argument(
        "--check-local-docker-images",
        action="store_true",
        help="Check whether docker-compose Neo4j/Browserless images are already available locally.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    applied_defaults = {}
    if args.local_neo4j_defaults:
        applied_defaults.update(apply_local_neo4j_env_defaults())

    wait_result = {}
    if int(args.wait_local_neo4j or 0) > 0 and is_local_neo4j_uri(os.environ.get("NEO4J_URI", "")):
        wait_result["neo4j"] = wait_for_port(
            "127.0.0.1",
            7687,
            timeout_seconds=int(args.wait_local_neo4j),
        )
        wait_result["neo4j_timeout_seconds"] = int(args.wait_local_neo4j)
    browserless_wait_ready = None
    if int(args.wait_local_browserless or 0) > 0:
        browserless_wait_ready = wait_for_port(
            "127.0.0.1",
            LOCAL_BROWSERLESS_PORT,
            timeout_seconds=int(args.wait_local_browserless),
        )
        wait_result["browserless"] = browserless_wait_ready
        wait_result["browserless_timeout_seconds"] = int(args.wait_local_browserless)
    flaresolverr_wait_ready = None
    if int(args.wait_local_flaresolverr or 0) > 0:
        flaresolverr_wait_ready = wait_for_port(
            "127.0.0.1",
            LOCAL_FLARESOLVERR_PORT,
            timeout_seconds=int(args.wait_local_flaresolverr),
        )
        wait_result["flaresolverr"] = flaresolverr_wait_ready
        wait_result["flaresolverr_timeout_seconds"] = int(args.wait_local_flaresolverr)

    browser_default_status = None
    if args.local_browser_render_defaults:
        browserless_port_available = bool(browserless_wait_ready) or is_port_open("127.0.0.1", LOCAL_BROWSERLESS_PORT)
        flaresolverr_port_available = bool(flaresolverr_wait_ready) or is_port_open(
            "127.0.0.1",
            LOCAL_FLARESOLVERR_PORT,
        )
        browser_defaults = apply_local_browser_render_env_defaults(
            prefer_browserless=bool(browserless_wait_ready),
            prefer_unlocker=bool(args.prefer_unlocker and flaresolverr_port_available),
        )
        applied_defaults.update(browser_defaults)
        browser_default_status = {
            "requested": True,
            **company_filing_playwright_browser_status(),
            "browserless_port_available": browserless_port_available,
            "flaresolverr_port_available": flaresolverr_port_available,
            "preferred_unlocker": bool(args.prefer_unlocker),
            "applied_env_keys": sorted(browser_defaults),
            "reason": None
            if browser_defaults
            else (
                "flaresolverr_or_browserless_port_or_playwright_dependency_missing_"
                "or_existing_render_fallback_configured"
            ),
        }
    if applied_defaults:
        clear_settings_cache()

    audit = audit_upgrade_capabilities(strict_external=args.strict_external)
    if applied_defaults:
        audit["local_dependency_defaults"] = {
            "applied_env_keys": sorted(applied_defaults),
            "note": "Defaults apply only to this audit process; .env is unchanged.",
        }
    if browser_default_status is not None:
        audit["local_browser_render_defaults"] = browser_default_status
    if wait_result:
        audit["local_dependency_wait"] = wait_result
    if args.check_local_docker_images:
        images = None
        if args.prefer_unlocker:
            images = {
                "neo4j": "neo4j:5-community",
                "browserless": "ghcr.io/browserless/chromium:latest",
                "flaresolverr": LOCAL_FLARESOLVERR_IMAGE,
            }
        audit["local_docker_images"] = local_docker_image_status(images)
    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_text(audit))
    return 1 if audit["failures"] else 0


def _format_text(audit: dict) -> str:
    implementation = audit.get("implementation") or {}
    deployment = audit.get("deployment") or {}
    lines = [
        f"Upgrade audit: {audit['overall_status']}",
        (
            f"Core implementation: {implementation.get('status', 'unknown')} "
            f"({implementation.get('ready', 0)}/{implementation.get('total_checks', 0)} ready)"
        ),
        (
            f"External integrations: {deployment.get('status', 'unknown')} "
            f"({deployment.get('ready', 0)}/{deployment.get('total_checks', 0)} ready)"
        ),
        (
            f"Checks: {audit['summary']['ready']} ready, "
            f"{audit['summary']['warnings']} warnings, "
            f"{audit['summary']['failures']} failures"
        ),
    ]
    local_defaults = audit.get("local_dependency_defaults")
    if local_defaults:
        lines.append(
            "Local defaults: applied "
            + ", ".join(local_defaults.get("applied_env_keys") or [])
            + " (current process only)"
        )
    browser_defaults = audit.get("local_browser_render_defaults")
    if browser_defaults:
        applied = browser_defaults.get("applied_env_keys") or []
        lines.append(
            "Local browser render defaults: "
            + (
                "applied " + ", ".join(applied)
                if applied
                else str(browser_defaults.get("reason") or "not applied")
            )
        )
    local_wait = audit.get("local_dependency_wait")
    if local_wait:
        wait_lines = []
        if "neo4j" in local_wait:
            wait_lines.append(
                f"Local Neo4j wait: {'ready' if local_wait.get('neo4j') else 'not ready'} "
                f"within {local_wait.get('neo4j_timeout_seconds', local_wait.get('timeout_seconds'))}s"
            )
        if "browserless" in local_wait:
            wait_lines.append(
                f"Local Browserless wait: {'ready' if local_wait.get('browserless') else 'not ready'} "
                f"within {local_wait.get('browserless_timeout_seconds')}s"
            )
        if "flaresolverr" in local_wait:
            wait_lines.append(
                f"Local FlareSolverr wait: {'ready' if local_wait.get('flaresolverr') else 'not ready'} "
                f"within {local_wait.get('flaresolverr_timeout_seconds')}s"
            )
        lines.extend(wait_lines)
    local_images = audit.get("local_docker_images")
    if local_images:
        image_lines = [
            f"{row['service']}={'present' if row.get('present') else 'missing'}"
            for row in local_images.get("images", [])
        ]
        lines.append("Local docker images: " + ", ".join(image_lines))
        if local_images.get("remediation"):
            lines.append("  fix: " + str(local_images["remediation"]))
    for check in audit["checks"]:
        marker = "OK" if check["severity"] == "pass" else "WARN" if check["severity"] == "warn" else "FAIL"
        optional = " optional" if check["optional"] else ""
        lines.append(
            f"- [{marker}{optional}] {check['area']}.{check['capability']}: "
            f"{check['label']} ({check['status']})"
        )
        if check["remediation"]:
            lines.append(f"  fix: {check['remediation']}")
    return "\n".join(lines)


def apply_local_neo4j_env_defaults() -> dict[str, str]:
    applied = {}
    for key, value in LOCAL_NEO4J_ENV_DEFAULTS.items():
        if os.environ.get(key):
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def apply_local_browser_render_env_defaults(
    *,
    prefer_browserless: bool = False,
    prefer_unlocker: bool = False,
) -> dict[str, str]:
    if os.environ.get("COMPANY_FILING_PROXY_URLS"):
        return {}
    if os.environ.get("COMPANY_FILING_BROWSER_RENDER_ENABLED") and os.environ.get(
        "COMPANY_FILING_BROWSER_RENDER_URL"
    ):
        return {}
    if os.environ.get("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"):
        return {}
    if prefer_unlocker:
        applied = {}
        for key, value in LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS.items():
            os.environ[key] = value
            applied[key] = value
        return applied
    if prefer_browserless or is_port_open("127.0.0.1", LOCAL_BROWSERLESS_PORT):
        applied = {}
        for key, value in LOCAL_BROWSER_RENDER_ENV_DEFAULTS.items():
            os.environ[key] = value
            applied[key] = value
        return applied
    if not company_filing_playwright_browser_status().get("browser_available"):
        return {}
    os.environ["COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"] = "true"
    return {"COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED": "true"}


def clear_settings_cache() -> None:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def is_local_neo4j_uri(uri: str) -> bool:
    return str(uri or "").startswith(
        (
            "neo4j://localhost:",
            "neo4j://127.0.0.1:",
            "bolt://localhost:",
            "bolt://127.0.0.1:",
        )
    )


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


if __name__ == "__main__":
    raise SystemExit(main())
