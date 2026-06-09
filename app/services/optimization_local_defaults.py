from __future__ import annotations


AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND = (
    ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
)
LOCAL_NEO4J_DEFAULTS_AUDIT_COMMAND = (
    ".venv/bin/python scripts/upgrade_audit.py --local-neo4j-defaults --wait-local-neo4j 20 --json"
)
LOCAL_BROWSER_RENDER_DEFAULTS_AUDIT_COMMAND = (
    ".venv/bin/python scripts/upgrade_audit.py "
    "--wait-local-browserless 20 --local-browser-render-defaults --json"
)
LOCAL_FLARESOLVERR_DEFAULTS_AUDIT_COMMAND = (
    ".venv/bin/python scripts/upgrade_audit.py "
    "--prefer-unlocker --wait-local-flaresolverr 20 "
    "--local-browser-render-defaults --json"
)
EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND = (
    ".venv/bin/python scripts/upgrade_audit.py "
    "--local-neo4j-defaults --wait-local-neo4j 20 "
    "--wait-local-browserless 20 --local-browser-render-defaults --json"
)
EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND = (
    ".venv/bin/python scripts/upgrade_audit.py "
    "--local-neo4j-defaults --prefer-unlocker "
    "--wait-local-neo4j 20 --wait-local-flaresolverr 20 "
    "--local-browser-render-defaults --json"
)


def local_defaults_verify_command(local_actions: list[dict]) -> str:
    if not local_actions:
        return ""
    capabilities = {
        str(action.get("capability") or "").strip()
        for action in local_actions
        if str(action.get("capability") or "").strip()
    }
    groups = {
        str((action.get("local_auto_default") or {}).get("group") or "").strip()
        for action in local_actions
        if isinstance(action.get("local_auto_default") or {}, dict)
    }
    has_neo4j = bool(
        groups.intersection({"neo4j"})
        or capabilities.intersection({"neo4j_import", "graphrag_live_cypher_query"})
    )
    has_unlocker = bool(
        groups.intersection({"flaresolverr"}) or "company_filing_high_risk_unlocker" in capabilities
    )
    has_browser_render = bool(
        groups.intersection({"browserless"})
        or "company_filing_browser_or_proxy_fallback" in capabilities
    )
    if has_neo4j and has_unlocker:
        return EXPLICIT_LOCAL_DEFAULTS_AUDIT_COMMAND
    if has_neo4j and has_browser_render:
        return EXPLICIT_LOCAL_BROWSERLESS_DEFAULTS_AUDIT_COMMAND
    if has_neo4j:
        return LOCAL_NEO4J_DEFAULTS_AUDIT_COMMAND
    if has_unlocker:
        return LOCAL_FLARESOLVERR_DEFAULTS_AUDIT_COMMAND
    if has_browser_render:
        return LOCAL_BROWSER_RENDER_DEFAULTS_AUDIT_COMMAND
    return AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND


def local_default_verify_commands(
    primary_command: str,
    local_actions: list[dict],
) -> list[str]:
    commands: list[str] = []
    for command in [
        primary_command,
        *[
            str((action.get("local_auto_default") or {}).get("verify_command") or "")
            for action in local_actions
            if isinstance(action.get("local_auto_default") or {}, dict)
        ],
        AUTO_LOCAL_DEFAULTS_AUDIT_COMMAND if local_actions else "",
    ]:
        command = command.strip()
        if command and command not in commands:
            commands.append(command)
    return commands


def local_default_capabilities(local_actions: list[dict]) -> list[dict]:
    capabilities: list[dict] = []
    for action in local_actions:
        capability = str(action.get("capability") or "").strip()
        if not capability:
            continue
        local_default = action.get("local_auto_default") or {}
        capabilities.append(
            {
                "capability": capability,
                "label": action.get("label") or capability,
                "group": local_default.get("group") if isinstance(local_default, dict) else "",
            }
        )
    return capabilities
