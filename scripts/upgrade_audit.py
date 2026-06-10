from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.data_sources.company_filing_render import (  # noqa: E402
    company_filing_playwright_browser_status,
)
from app.services.local_dependency_diagnostics import (  # noqa: E402
    LOCAL_BROWSERLESS_PORT,
    LOCAL_BROWSER_RENDER_ENV_DEFAULTS,
    LOCAL_CHROMA_ENV_DEFAULTS,
    LOCAL_DOCKER_DEPENDENCY_IMAGES,
    LOCAL_FLARESOLVERR_IMAGE,
    LOCAL_FLARESOLVERR_PORT,
    LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS,
    local_docker_image_status,
)
from app.services.supply_chain_graph_neo4j import LOCAL_NEO4J_ENV_DEFAULTS  # noqa: E402
from app.services.upgrade_audit import audit_upgrade_capabilities  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit system readiness against the upgrade objective."
    )
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
        "--auto-local-defaults",
        action="store_true",
        help=(
            "Auto-apply local defaults for already reachable Neo4j, Chroma, Browserless, "
            "or FlareSolverr services in this audit process without editing .env."
        ),
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
        "--local-chroma-defaults",
        action="store_true",
        help="Apply local docker-compose Chroma HTTP defaults for this audit process without editing .env.",
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
        "--wait-local-chroma",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait for localhost Chroma heartbeat before auditing when local Chroma settings are active.",
    )
    parser.add_argument(
        "--check-local-docker-images",
        action="store_true",
        help="Check whether docker-compose Neo4j/Browserless images are already available locally.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    applied_defaults = {}
    auto_defaults_status = None
    auto_applied_defaults = {}
    wait_result = {}
    if args.auto_local_defaults:
        auto_defaults_status = {
            "requested": True,
            "detected": {},
            "applied_groups": [],
            "applied_env_keys": [],
            "note": "Auto defaults apply only to this audit process; .env is unchanged.",
        }
        neo4j_ready = _detect_local_neo4j_for_auto_defaults(
            wait_seconds=int(args.wait_local_neo4j or 0),
            wait_result=wait_result,
        )
        auto_defaults_status["detected"]["neo4j"] = neo4j_ready
        if neo4j_ready and not args.local_neo4j_defaults:
            neo4j_defaults = apply_local_neo4j_env_defaults()
            applied_defaults.update(neo4j_defaults)
            auto_applied_defaults.update(neo4j_defaults)
            if neo4j_defaults:
                auto_defaults_status["applied_groups"].append("neo4j")

    if args.local_neo4j_defaults:
        applied_defaults.update(apply_local_neo4j_env_defaults())
    chroma_default_status = None
    if args.auto_local_defaults:
        chroma_ready = _detect_local_chroma_for_auto_defaults(
            wait_seconds=int(args.wait_local_chroma or 0),
            wait_result=wait_result,
        )
        auto_defaults_status["detected"]["chroma"] = chroma_ready
        if chroma_ready and not args.local_chroma_defaults:
            chroma_defaults = apply_local_chroma_env_defaults()
            applied_defaults.update(chroma_defaults)
            auto_applied_defaults.update(chroma_defaults)
            if chroma_defaults:
                auto_defaults_status["applied_groups"].append("chroma")
            chroma_default_status = {
                "requested": True,
                "auto_detected": True,
                "url": os.environ.get("CHROMA_API_URL")
                or LOCAL_CHROMA_ENV_DEFAULTS["CHROMA_API_URL"],
                "applied_env_keys": sorted(chroma_defaults),
                "reason": None if chroma_defaults else "existing_chroma_env_configured",
            }
    if args.local_chroma_defaults:
        chroma_defaults = apply_local_chroma_env_defaults()
        applied_defaults.update(chroma_defaults)
        chroma_default_status = {
            "requested": True,
            "auto_detected": False,
            "url": os.environ.get("CHROMA_API_URL") or LOCAL_CHROMA_ENV_DEFAULTS["CHROMA_API_URL"],
            "applied_env_keys": sorted(chroma_defaults),
            "reason": None if chroma_defaults else "existing_chroma_env_configured",
        }

    if (
        int(args.wait_local_neo4j or 0) > 0
        and "neo4j" not in wait_result
        and is_local_neo4j_uri(os.environ.get("NEO4J_URI", ""))
    ):
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
    if int(args.wait_local_chroma or 0) > 0 and "chroma" not in wait_result:
        chroma_api_url = os.environ.get("CHROMA_API_URL") or LOCAL_CHROMA_ENV_DEFAULTS[
            "CHROMA_API_URL"
        ]
        wait_result["chroma"] = wait_for_http_ok(
            chroma_health_url(chroma_api_url),
            timeout_seconds=int(args.wait_local_chroma),
        )
        wait_result["chroma_timeout_seconds"] = int(args.wait_local_chroma)

    browser_default_status = None
    if args.auto_local_defaults and auto_defaults_status is not None:
        browserless_port_available = bool(browserless_wait_ready) or is_port_open(
            "127.0.0.1",
            LOCAL_BROWSERLESS_PORT,
        )
        flaresolverr_port_available = bool(flaresolverr_wait_ready) or is_port_open(
            "127.0.0.1",
            LOCAL_FLARESOLVERR_PORT,
        )
        auto_defaults_status["detected"]["browserless"] = browserless_port_available
        auto_defaults_status["detected"]["flaresolverr"] = flaresolverr_port_available
        if (
            (browserless_port_available or flaresolverr_port_available)
            and not args.local_browser_render_defaults
        ):
            browser_defaults = apply_local_browser_render_env_defaults(
                prefer_browserless=browserless_port_available,
                prefer_unlocker=bool(flaresolverr_port_available or args.prefer_unlocker),
            )
            applied_defaults.update(browser_defaults)
            auto_applied_defaults.update(browser_defaults)
            if browser_defaults:
                auto_defaults_status["applied_groups"].append(
                    "flaresolverr" if flaresolverr_port_available else "browserless"
                )
            browser_default_status = {
                "requested": True,
                "auto_detected": True,
                **company_filing_playwright_browser_status(),
                "browserless_port_available": browserless_port_available,
                "flaresolverr_port_available": flaresolverr_port_available,
                "preferred_unlocker": bool(flaresolverr_port_available or args.prefer_unlocker),
                "applied_env_keys": sorted(browser_defaults),
                "reason": None
                if browser_defaults
                else (
                    "flaresolverr_or_browserless_port_or_playwright_dependency_missing_"
                    "or_existing_render_fallback_configured"
                ),
            }
    if args.local_browser_render_defaults:
        browserless_port_available = bool(browserless_wait_ready) or is_port_open(
            "127.0.0.1", LOCAL_BROWSERLESS_PORT
        )
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
            "auto_detected": False,
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
    if auto_defaults_status is not None:
        auto_defaults_status["applied_env_keys"] = sorted(auto_applied_defaults)
        auto_defaults_status["applied_groups"] = sorted(
            set(auto_defaults_status["applied_groups"])
        )

    audit = audit_upgrade_capabilities(strict_external=args.strict_external)
    if auto_defaults_status is not None:
        audit["local_dependency_auto_defaults"] = auto_defaults_status
    if applied_defaults:
        audit["local_dependency_defaults"] = {
            "applied_env_keys": sorted(applied_defaults),
            "note": "Defaults apply only to this audit process; .env is unchanged.",
        }
    if browser_default_status is not None:
        audit["local_browser_render_defaults"] = browser_default_status
    if chroma_default_status is not None:
        audit["local_chroma_defaults"] = chroma_default_status
    if wait_result:
        audit["local_dependency_wait"] = wait_result
    if args.check_local_docker_images:
        images = None
        if args.prefer_unlocker:
            images = {
                **LOCAL_DOCKER_DEPENDENCY_IMAGES,
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
    summary = audit.get("summary") or {}
    warning_text = f"{summary.get('warnings', 0)} warnings"
    optional_warnings = int(summary.get("optional_warnings") or 0)
    if optional_warnings:
        warning_text += f", {optional_warnings} optional deployment warnings"
    lines = [
        f"Upgrade audit: {audit['overall_status']}",
        (
            f"Core implementation: {implementation.get('status', 'unknown')} "
            f"({implementation.get('ready', 0)}/{implementation.get('total_checks', 0)} ready)"
        ),
        (
            f"External integrations: {deployment.get('status', 'unknown')} "
            f"({deployment.get('ready', 0)}/{deployment.get('total_checks', 0)} ready; "
            f"blocking={deployment.get('blocking_status') or summary.get('deployment_blocking_status') or deployment.get('status', 'unknown')})"
        ),
        (
            f"Checks: {summary.get('ready', 0)} ready, "
            f"{warning_text}, "
            f"{summary.get('failures', 0)} failures"
        ),
    ]
    if summary.get("deployment_optional_only"):
        lines.append(
            "Deployment note: no blocking deployment gaps; remaining warnings are optional external integrations."
        )
    enablement_summary = (
        audit.get("external_deployment_enablement")
        if isinstance(audit.get("external_deployment_enablement"), dict)
        else {}
    )
    if enablement_summary.get("total"):
        lines.append(
            "External enablement: "
            f"pending={int(enablement_summary.get('pending') or 0)}; "
            f"blocking_pending={int(enablement_summary.get('blocking_pending') or 0)}; "
            f"optional_pending={int(enablement_summary.get('nonblocking_optional_pending') or 0)}; "
            f"free_local={int(enablement_summary.get('free_local_pending') or 0)}; "
            f"local_action={int(enablement_summary.get('local_action_available') or 0)}; "
            f"quota_or_external={int(enablement_summary.get('quota_or_external_pending') or 0)}; "
            f"paid_external={int(enablement_summary.get('paid_external_pending') or 0)}"
        )
        if enablement_summary.get("primary_next_action"):
            lines.append(
                "External next action: " + str(enablement_summary["primary_next_action"])
            )
    pending_gap_counts = (
        audit.get("external_deployment_pending_gap_action_counts")
        if isinstance(audit.get("external_deployment_pending_gap_action_counts"), dict)
        else {}
    )
    if pending_gap_counts:
        lines.append(
            "External gap actions: "
            f"local_action={int(pending_gap_counts.get('local_action') or 0)}; "
            f"quota_or_external={int(pending_gap_counts.get('quota_or_external') or 0)}; "
            f"paid_external={int(pending_gap_counts.get('paid_external') or 0)}; "
            f"manual_configuration={int(pending_gap_counts.get('manual_configuration') or 0)}"
        )
    local_projection = (
        audit.get("external_deployment_local_projection")
        if isinstance(audit.get("external_deployment_local_projection"), dict)
        else {}
    )
    if local_projection:
        lines.append(
            "Effective external gaps: "
            f"pending={int(local_projection.get('current_pending') or 0)} -> "
            f"{int(local_projection.get('remaining_pending') or 0)} after available local defaults; "
            f"blocking={int(local_projection.get('remaining_blocking_pending') or 0)}; "
            f"optional={int(local_projection.get('remaining_optional_pending') or 0)}; "
            f"paid_external={int(local_projection.get('remaining_paid_external_pending') or 0)}; "
            f"local_defaults={int(local_projection.get('available_local_default_gap_count') or 0)}"
        )
        if local_projection.get("next_action"):
            lines.append("Effective next action: " + str(local_projection["next_action"]))
    auto_defaults = audit.get("local_dependency_auto_defaults")
    if auto_defaults:
        detected = auto_defaults.get("detected") or {}
        detected_ready = ", ".join(
            service for service, ready in detected.items() if ready
        ) or "-"
        applied_groups = ", ".join(auto_defaults.get("applied_groups") or []) or "-"
        lines.append(
            "Auto local defaults: "
            f"detected={detected_ready}; applied={applied_groups}"
        )
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
    chroma_defaults = audit.get("local_chroma_defaults")
    if chroma_defaults:
        applied = chroma_defaults.get("applied_env_keys") or []
        lines.append(
            "Local Chroma defaults: "
            + (
                "applied " + ", ".join(applied)
                if applied
                else str(chroma_defaults.get("reason") or "not applied")
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
        if "chroma" in local_wait:
            wait_lines.append(
                f"Local Chroma wait: {'ready' if local_wait.get('chroma') else 'not ready'} "
                f"within {local_wait.get('chroma_timeout_seconds')}s"
            )
        lines.extend(wait_lines)
    local_runtime = audit.get("local_dependencies")
    if isinstance(local_runtime, dict) and local_runtime:
        open_services = ", ".join(local_runtime.get("open_services") or []) or "-"
        missing_core = ", ".join(local_runtime.get("missing_core_services") or []) or "-"
        lines.append(
            "Local dependency runtime: "
            f"{local_runtime.get('status', 'unknown')}; "
            f"open={open_services}; missing_core={missing_core}"
        )
        last_start = (
            local_runtime.get("last_start")
            if isinstance(local_runtime.get("last_start"), dict)
            else {}
        )
        if last_start.get("available"):
            lines.append(
                "Local dependency last start: "
                f"{last_start.get('status', 'unknown')} at {last_start.get('updated_at', '-')}; "
                f"path={last_start.get('path', '-')}"
            )
    local_images = audit.get("local_docker_images")
    if local_images:
        image_lines = [
            f"{row['service']}={'present' if row.get('present') else 'missing'}"
            for row in local_images.get("images", [])
        ]
        lines.append("Local docker images: " + ", ".join(image_lines))
        if local_images.get("remediation"):
            lines.append("  fix: " + str(local_images["remediation"]))
    pending_gap_rows = _pending_gap_rows_by_capability(audit)
    for check in audit["checks"]:
        marker = (
            "OK"
            if check["severity"] == "pass"
            else "WARN"
            if check["severity"] == "warn"
            else "FAIL"
        )
        optional = " optional" if check["optional"] else ""
        lines.append(
            f"- [{marker}{optional}] {check['area']}.{check['capability']}: "
            f"{check['label']} ({check['status']})"
        )
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
        if check["remediation"]:
            lines.append(f"  fix: {check['remediation']}")
        gap_row = pending_gap_rows.get(str(check.get("capability") or ""))
        if gap_row and check["severity"] != "pass":
            lines.append(
                "  action: "
                f"{gap_row.get('action_type')} "
                f"({gap_row.get('decision')}; {gap_row.get('local_action_state')})"
            )
            local_command = str(gap_row.get("local_action_command") or "-")
            if local_command != "-":
                lines.append(f"  command: {local_command}")
    return "\n".join(lines)


def _pending_gap_rows_by_capability(audit: dict) -> dict[str, dict]:
    rows = audit.get("external_deployment_pending_gaps")
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("capability") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("capability") or "")
    }


def apply_local_neo4j_env_defaults() -> dict[str, str]:
    applied = {}
    for key, value in LOCAL_NEO4J_ENV_DEFAULTS.items():
        if os.environ.get(key):
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def apply_local_chroma_env_defaults() -> dict[str, str]:
    if os.environ.get("USE_CHROMA") or os.environ.get("CHROMA_API_URL"):
        return {}
    applied = {}
    for key, value in LOCAL_CHROMA_ENV_DEFAULTS.items():
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


def _detect_local_neo4j_for_auto_defaults(
    *,
    wait_seconds: int,
    wait_result: dict,
) -> bool:
    if wait_seconds > 0:
        ready = wait_for_port("127.0.0.1", 7687, timeout_seconds=wait_seconds)
        wait_result["neo4j"] = ready
        wait_result["neo4j_timeout_seconds"] = wait_seconds
        return ready
    return is_port_open("127.0.0.1", 7687)


def _detect_local_chroma_for_auto_defaults(
    *,
    wait_seconds: int,
    wait_result: dict,
) -> bool:
    url = chroma_health_url(
        os.environ.get("CHROMA_API_URL") or LOCAL_CHROMA_ENV_DEFAULTS["CHROMA_API_URL"]
    )
    if wait_seconds > 0:
        ready = wait_for_http_ok(url, timeout_seconds=wait_seconds)
        wait_result["chroma"] = ready
        wait_result["chroma_timeout_seconds"] = wait_seconds
        return ready
    return http_ok(url)


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


def wait_for_http_ok(url: str, timeout_seconds: int) -> bool:
    deadline = time.time() + max(0, timeout_seconds)
    while time.time() < deadline:
        if http_ok(url):
            return True
        time.sleep(0.5)
    return http_ok(url)


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            return 200 <= int(response.getcode()) < 300
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def chroma_health_url(api_url: str) -> str:
    return str(api_url or LOCAL_CHROMA_ENV_DEFAULTS["CHROMA_API_URL"]).rstrip(
        "/"
    ) + "/api/v2/heartbeat"


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


if __name__ == "__main__":
    raise SystemExit(main())
