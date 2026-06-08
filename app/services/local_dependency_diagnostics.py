from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path


LOCAL_DOCKER_DEPENDENCY_IMAGES = {
    "redis": "redis:7-alpine",
    "postgres": "postgres:16-alpine",
    "neo4j": "neo4j:5-community",
    "browserless": "ghcr.io/browserless/chromium:latest",
    "chroma": "chromadb/chroma:latest",
}
LOCAL_DEPENDENCY_PORTS = {
    "redis": {"label": "Redis", "port": 6379, "role": "Celery broker/backend 與快取"},
    "postgres": {"label": "Postgres", "port": 5432, "role": "正式資料庫"},
    "neo4j": {"label": "Neo4j", "port": 7687, "role": "GraphRAG live graph"},
    "browserless": {"label": "Browserless", "port": 3000, "role": "公司文件瀏覽器 render"},
    "chroma": {"label": "Chroma", "port": 8001, "role": "向量資料庫服務"},
    "flaresolverr": {"label": "FlareSolverr", "port": 8191, "role": "MOPS/TWSE 高風險 unlocker"},
}
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
    "verify_flaresolverr": (
        ".venv/bin/python scripts/upgrade_audit.py "
        "--prefer-unlocker --wait-local-flaresolverr 20 --local-browser-render-defaults --json"
    ),
}


def local_dependency_runtime_status(
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    port_open_func: Callable[[str, int], bool] | None = None,
) -> dict:
    project_root = root or Path(__file__).resolve().parents[2]
    env = environ or os.environ
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
    return {
        "collector_path": "app/services/local_dependency_diagnostics.py",
        "compose_path": "docker-compose.yml",
        "compose_file_present": compose_path.exists(),
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
        "commands": dict(LOCAL_DEPENDENCY_COMMANDS),
        "configured_env": _local_dependency_configured_env(env),
    }


def is_local_port_open(host: str, port: int, *, timeout_seconds: float = 0.1) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            return True
    except OSError:
        return False


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
