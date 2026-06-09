from __future__ import annotations

import os
import json
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from app.services.supply_chain_graph_neo4j import LOCAL_NEO4J_ENV_DEFAULTS


LOCAL_DOCKER_DEPENDENCY_IMAGES = {
    "redis": "redis:7-alpine",
    "postgres": "postgres:16-alpine",
    "neo4j": "neo4j:5-community",
    "browserless": "ghcr.io/browserless/chromium:latest",
    "chroma": "chromadb/chroma:latest",
}
LOCAL_NEO4J_PORT = 7687
LOCAL_BROWSERLESS_PORT = 3000
LOCAL_FLARESOLVERR_PORT = 8191
LOCAL_CHROMA_PORT = 8001
LOCAL_DEPENDENCY_PORTS = {
    "redis": {"label": "Redis", "port": 6379, "role": "Celery broker/backend 與快取"},
    "postgres": {"label": "Postgres", "port": 5432, "role": "正式資料庫"},
    "neo4j": {"label": "Neo4j", "port": LOCAL_NEO4J_PORT, "role": "GraphRAG live graph"},
    "browserless": {
        "label": "Browserless",
        "port": LOCAL_BROWSERLESS_PORT,
        "role": "公司文件瀏覽器 render",
    },
    "chroma": {"label": "Chroma", "port": LOCAL_CHROMA_PORT, "role": "向量資料庫服務"},
    "flaresolverr": {
        "label": "FlareSolverr",
        "port": LOCAL_FLARESOLVERR_PORT,
        "role": "MOPS/TWSE 高風險 unlocker",
    },
}
LOCAL_CHROMA_API_URL = f"http://127.0.0.1:{LOCAL_CHROMA_PORT}"
LOCAL_CHROMA_ENV_DEFAULTS = {
    "USE_CHROMA": "true",
    "CHROMA_API_URL": LOCAL_CHROMA_API_URL,
}
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
LOCAL_DEPENDENCY_COMMANDS = {
    "start_core": ".venv/bin/python scripts/start_system.py --start-dependencies",
    "start_unlocker": ".venv/bin/python scripts/start_system.py --start-dependencies --prefer-unlocker",
    "verify_neo4j": (
        ".venv/bin/python scripts/upgrade_audit.py "
        "--local-neo4j-defaults --wait-local-neo4j 20 --json"
    ),
    "verify_browserless": (
        ".venv/bin/python scripts/upgrade_audit.py "
        "--wait-local-browserless 20 --local-browser-render-defaults --json"
    ),
    "verify_chroma": (
        ".venv/bin/python scripts/upgrade_audit.py "
        "--local-chroma-defaults --wait-local-chroma 20 --json"
    ),
    "verify_flaresolverr": (
        ".venv/bin/python scripts/upgrade_audit.py "
        "--prefer-unlocker --wait-local-flaresolverr 20 --local-browser-render-defaults --json"
    ),
}
LOCAL_DEPENDENCY_START_STATUS_PATH = Path("data/local_dependency_start_status.json")


def local_dependency_runtime_status(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    port_open_func: Callable[[str, int], bool] | None = None,
    chroma_http_ready_func: Callable[[str], bool] | None = None,
) -> dict:
    project_root = root or Path(__file__).resolve().parents[2]
    env = os.environ if environ is None else environ
    port_checker = port_open_func or is_local_port_open
    ports = [
        {
            "service": service,
            "label": str(metadata["label"]),
            "host": "127.0.0.1",
            "port": int(metadata["port"]),
            "open": bool(port_checker("127.0.0.1", int(metadata["port"]))),
            "role": str(metadata["role"]),
        }
        for service, metadata in LOCAL_DEPENDENCY_PORTS.items()
    ]
    open_services = [row["service"] for row in ports if row["open"]]
    core_services = ["redis", "postgres", "neo4j", "browserless", "chroma"]
    missing_core_services = [service for service in core_services if service not in open_services]
    compose_path = project_root / "docker-compose.yml"
    compose_file_present = compose_path.exists()
    commands = dict(LOCAL_DEPENDENCY_COMMANDS)
    configured_env = _local_dependency_configured_env(env)
    auto_defaults_preview = local_dependency_auto_defaults_preview(
        ports=ports,
        configured_env=configured_env,
        environ=env,
        commands=commands,
        chroma_http_ready_func=chroma_http_ready_func,
    )
    return {
        "collector_path": "app/services/local_dependency_diagnostics.py",
        "compose_path": "docker-compose.yml",
        "compose_file_present": compose_file_present,
        "status": "ready"
        if not missing_core_services
        else "partial"
        if open_services
        else "not_running",
        "ports": ports,
        "open_services": open_services,
        "missing_core_services": missing_core_services,
        "core_ready": not missing_core_services,
        "unlocker_ready": "flaresolverr" in open_services,
        "commands": commands,
        "configured_env": configured_env,
        "auto_defaults_preview": auto_defaults_preview,
        "last_start": local_dependency_last_start_status(root=project_root),
        "repair_plan": local_dependency_repair_plan(
            compose_file_present=compose_file_present,
            ports=ports,
            missing_core_services=missing_core_services,
            configured_env=configured_env,
            commands=commands,
        ),
    }


def local_dependency_auto_defaults_preview(
    *,
    ports: list[dict],
    configured_env: dict,
    environ: Mapping[str, str] | None = None,
    commands: dict[str, str] | None = None,
    chroma_http_ready_func: Callable[[str], bool] | None = None,
) -> dict:
    env = os.environ if environ is None else environ
    command_map = commands or dict(LOCAL_DEPENDENCY_COMMANDS)
    chroma_url = str(env.get("CHROMA_API_URL") or LOCAL_CHROMA_API_URL)
    chroma_heartbeat_ready = bool(
        (chroma_http_ready_func or local_chroma_heartbeat_ok)(chroma_health_url(chroma_url))
    )
    detected = {
        "neo4j": _local_dependency_port_open(ports, "neo4j"),
        "chroma": chroma_heartbeat_ready,
        "browserless": _local_dependency_port_open(ports, "browserless"),
        "flaresolverr": _local_dependency_port_open(ports, "flaresolverr"),
    }
    groups: list[dict] = []
    _append_auto_default_group(
        groups,
        "neo4j",
        detected=detected["neo4j"],
        env_defaults=LOCAL_NEO4J_ENV_DEFAULTS,
        applied_env_keys=[
            key for key in LOCAL_NEO4J_ENV_DEFAULTS if not str(env.get(key) or "").strip()
        ],
        configured=bool(configured_env.get("neo4j_uri_configured")),
        verify_command=command_map.get("verify_neo4j") or "-",
        capabilities=[
            ("ai_rag", "neo4j_import"),
            ("ai_rag", "graphrag_live_cypher_query"),
        ],
    )
    _append_auto_default_group(
        groups,
        "chroma",
        detected=detected["chroma"],
        env_defaults=LOCAL_CHROMA_ENV_DEFAULTS,
        applied_env_keys=(
            []
            if env.get("USE_CHROMA") or env.get("CHROMA_API_URL")
            else list(LOCAL_CHROMA_ENV_DEFAULTS)
        ),
        configured=bool(configured_env.get("chroma_api_url_configured")),
        verify_command=command_map.get("verify_chroma") or "-",
        capabilities=[
            ("ai_rag", "hybrid_search"),
        ],
    )
    render_group = "flaresolverr" if detected["flaresolverr"] else "browserless"
    render_defaults = (
        LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS
        if render_group == "flaresolverr"
        else LOCAL_BROWSER_RENDER_ENV_DEFAULTS
    )
    render_detected = bool(detected["flaresolverr"] or detected["browserless"])
    render_skip = bool(
        env.get("COMPANY_FILING_PROXY_URLS")
        or (
            env.get("COMPANY_FILING_BROWSER_RENDER_ENABLED")
            and env.get("COMPANY_FILING_BROWSER_RENDER_URL")
        )
        or env.get("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED")
    )
    _append_auto_default_group(
        groups,
        render_group,
        detected=render_detected,
        env_defaults=render_defaults,
        applied_env_keys=[] if render_skip else list(render_defaults),
        configured=bool(
            configured_env.get("browser_render_enabled")
            and (
                configured_env.get("browserless_url_configured")
                or configured_env.get("flaresolverr_url_configured")
            )
        ),
        verify_command=(
            command_map.get("verify_flaresolverr")
            if render_group == "flaresolverr"
            else command_map.get("verify_browserless")
        )
        or "-",
        capabilities=[
            (
                "data_business_logic",
                "company_filing_high_risk_unlocker"
                if render_group == "flaresolverr"
                else "company_filing_browser_or_proxy_fallback",
            )
        ],
    )
    would_apply_groups = [
        str(group["group"]) for group in groups if group["detected"] and group["would_apply"]
    ]
    already_configured_groups = [
        str(group["group"])
        for group in groups
        if group["detected"] and group["configured"] and not group["would_apply"]
    ]
    capability_matches = [
        match
        for group in groups
        if group["detected"] and (group["would_apply"] or group["configured"])
        for match in _auto_default_capability_matches(group)
    ]
    return {
        "collector_path": "app/services/local_dependency_diagnostics.py",
        "mode": "status_preview",
        "compatible_audit_command": (
            ".venv/bin/python scripts/upgrade_audit.py --auto-local-defaults --json"
        ),
        "note": "Status preview only; no environment variables are changed by /services/status.",
        "detected": detected,
        "groups": groups,
        "would_apply_groups": sorted(would_apply_groups),
        "would_apply_env_keys": sorted(
            {
                str(key)
                for group in groups
                if group["detected"] and group["would_apply"]
                for key in group.get("applied_env_keys") or []
            }
        ),
        "already_configured_groups": sorted(already_configured_groups),
        "capability_matches": capability_matches,
        "local_action_available_count": len(capability_matches),
    }


def local_dependency_last_start_status(*, root: Path | None = None) -> dict:
    project_root = root or Path(__file__).resolve().parents[2]
    status_path = project_root / LOCAL_DEPENDENCY_START_STATUS_PATH
    base = {
        "available": False,
        "path": LOCAL_DEPENDENCY_START_STATUS_PATH.as_posix(),
    }
    if not status_path.exists():
        return {
            **base,
            "status": "missing",
            "message": "尚未透過 scripts/start_system.py --start-dependencies 記錄本機依賴啟動結果。",
        }
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            **base,
            "status": "invalid",
            "message": f"無法讀取本機依賴啟動紀錄：{exc}",
        }
    if not isinstance(payload, dict):
        return {
            **base,
            "status": "invalid",
            "message": "本機依賴啟動紀錄格式錯誤。",
        }
    return {
        **payload,
        "available": True,
        "path": LOCAL_DEPENDENCY_START_STATUS_PATH.as_posix(),
    }


def local_dependency_repair_plan(
    *,
    compose_file_present: bool,
    ports: list[dict],
    missing_core_services: list[str],
    configured_env: dict,
    commands: dict[str, str],
) -> list[dict[str, str]]:
    if not compose_file_present:
        return [
            {
                "item": "docker-compose.yml",
                "state": "缺少",
                "next_step": "確認目前工作目錄是專案根目錄，且 docker-compose.yml 存在。",
                "repair_command": "-",
                "verify_command": "ls docker-compose.yml",
                "severity": "error",
            }
        ]
    rows = [
        {
            "item": _local_dependency_service_label(service),
            "state": "未偵測",
            "next_step": f"{_local_dependency_service_role(service)}。啟動核心本機依賴後重新檢查。",
            "repair_command": commands.get("start_core") or "-",
            "verify_command": _local_dependency_verify_command(service, commands),
            "severity": "error",
        }
        for service in missing_core_services
    ]
    if configured_env.get("flaresolverr_url_configured") and not _local_dependency_port_open(
        ports,
        "flaresolverr",
    ):
        rows.append(
            {
                "item": "FlareSolverr unlocker",
                "state": "未偵測",
                "next_step": "已配置本機 FlareSolverr URL；啟動 unlocker profile，或改用 Browserless/Playwright。",
                "repair_command": commands.get("start_unlocker") or "-",
                "verify_command": commands.get("verify_flaresolverr") or "-",
                "severity": "warning",
            }
        )
    return rows


def is_local_port_open(host: str, port: int, *, timeout_seconds: float = 0.1) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def local_chroma_heartbeat_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return 200 <= int(response.getcode()) < 300
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def chroma_health_url(api_url: str) -> str:
    return str(api_url or LOCAL_CHROMA_API_URL).rstrip("/") + "/api/v2/heartbeat"


def local_docker_image_status(images: dict[str, str] | None = None) -> dict:
    image_map = images or LOCAL_DOCKER_DEPENDENCY_IMAGES
    rows = []
    docker_available = True
    docker_error = None
    for service, image in image_map.items():
        try:
            completed = subprocess.run(
                ["docker", "image", "inspect", image],
                check=False,
                text=True,
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            docker_available = False
            docker_error = "docker_not_found"
            rows.append(
                {"service": service, "image": image, "present": False, "error": docker_error}
            )
            continue
        except subprocess.TimeoutExpired:
            docker_error = "docker_image_inspect_timeout"
            rows.append(
                {"service": service, "image": image, "present": False, "error": docker_error}
            )
            continue
        present = completed.returncode == 0
        rows.append(
            {
                "service": service,
                "image": image,
                "present": present,
                "error": None if present else (completed.stderr or completed.stdout or "").strip(),
            }
        )
    missing = [row for row in rows if not row.get("present")]
    return {
        "docker_available": docker_available,
        "docker_error": docker_error,
        "images": rows,
        "all_present": not missing,
        "missing_services": [row["service"] for row in missing],
        "remediation": None
        if not missing
        else "docker compose pull " + " ".join(row["service"] for row in missing),
    }


def _local_dependency_service_label(service: str) -> str:
    metadata = LOCAL_DEPENDENCY_PORTS.get(service) or {}
    return str(metadata.get("label") or service)


def _local_dependency_service_role(service: str) -> str:
    metadata = LOCAL_DEPENDENCY_PORTS.get(service) or {}
    return str(metadata.get("role") or "本機依賴服務")


def _local_dependency_verify_command(service: str, commands: dict[str, str]) -> str:
    service_commands = {
        "neo4j": commands.get("verify_neo4j"),
        "browserless": commands.get("verify_browserless"),
        "chroma": commands.get("verify_chroma"),
    }
    return str(service_commands.get(service) or ".venv/bin/python scripts/upgrade_audit.py --json")


def _local_dependency_port_open(ports: list[dict], service: str) -> bool:
    for row in ports:
        if isinstance(row, dict) and row.get("service") == service:
            return bool(row.get("open"))
    return False


def _append_auto_default_group(
    groups: list[dict],
    group: str,
    *,
    detected: bool,
    env_defaults: Mapping[str, str],
    applied_env_keys: list[str],
    configured: bool,
    verify_command: str,
    capabilities: list[tuple[str, str]],
) -> None:
    groups.append(
        {
            "group": group,
            "detected": bool(detected),
            "configured": bool(configured),
            "would_apply": bool(detected and applied_env_keys),
            "applied_env_keys": sorted(applied_env_keys) if detected else [],
            "default_env_keys": sorted(env_defaults),
            "verify_command": verify_command,
            "capabilities": [
                {"area": area, "capability": capability}
                for area, capability in capabilities
            ],
        }
    )


def _auto_default_capability_matches(group: dict) -> list[dict]:
    state = "already_configured" if group.get("configured") else "would_apply"
    return [
        {
            "area": capability.get("area"),
            "capability": capability.get("capability"),
            "group": group.get("group"),
            "state": state,
            "would_apply": bool(group.get("would_apply")),
            "configured": bool(group.get("configured")),
            "verify_command": group.get("verify_command") or "-",
            "env_keys": group.get("applied_env_keys") or group.get("default_env_keys") or [],
        }
        for capability in group.get("capabilities") or []
        if isinstance(capability, dict)
    ]


def _local_dependency_configured_env(env: Mapping[str, str]) -> dict:
    browser_render_url = str(env.get("COMPANY_FILING_BROWSER_RENDER_URL") or "")
    return {
        "neo4j_uri_configured": bool(env.get("NEO4J_URI")),
        "neo4j_uri_local": _is_local_url_value(str(env.get("NEO4J_URI") or ""), ("7687",)),
        "browser_render_enabled": str(
            env.get("COMPANY_FILING_BROWSER_RENDER_ENABLED") or ""
        ).lower()
        == "true",
        "browserless_url_configured": "127.0.0.1:3000" in browser_render_url
        or "localhost:3000" in browser_render_url,
        "flaresolverr_url_configured": "127.0.0.1:8191" in browser_render_url
        or "localhost:8191" in browser_render_url,
        "playwright_render_enabled": str(
            env.get("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED") or ""
        ).lower()
        == "true",
        "chroma_api_url_configured": bool(env.get("CHROMA_API_URL")),
    }


def _is_local_url_value(value: str, port_markers: tuple[str, ...]) -> bool:
    if not value:
        return False
    return ("localhost" in value or "127.0.0.1" in value) and any(
        marker in value for marker in port_markers
    )
