from __future__ import annotations

import argparse
import importlib
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app.data_sources.company_filings import company_filing_playwright_browser_status
from app.services.local_dependency_diagnostics import local_docker_image_status
from app.services.schedule_config import ScheduleConfigStore
from app.services.supply_chain_graph_neo4j import LOCAL_NEO4J_ENV_DEFAULTS
from app.services.upgrade_audit import audit_upgrade_capabilities


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / ".run"
LOG_DIR = ROOT / "logs"
API_HOST = "127.0.0.1"
API_PORT = 8000
STREAMLIT_HOST = "0.0.0.0"
STREAMLIT_PORT = 8501
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the stock analysis system.")
    parser.add_argument("--open-browser", action="store_true", help="Open Streamlit in the default browser.")
    parser.add_argument(
        "--start-dependencies",
        action="store_true",
        help="Start docker-compose dependencies: Redis, Postgres, Neo4j, and Browserless.",
    )
    parser.add_argument(
        "--prefer-unlocker",
        action="store_true",
        help=(
            "When starting dependencies, also start FlareSolverr and prefer it for company filing "
            "browser render fallback."
        ),
    )
    parser.add_argument(
        "--pull-missing-dependencies",
        action="store_true",
        help="Allow Docker Compose to download missing dependency images during startup.",
    )
    parser.add_argument(
        "--skip-upgrade-check",
        action="store_true",
        help="Skip the AI/RAG upgrade capability preflight report.",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Skip startup Alembic migrations. Use only when an external deploy step already migrated the DB.",
    )
    parser.add_argument(
        "--strict-upgrade-check",
        action="store_true",
        help="Treat optional external integrations, such as live Neo4j import, as required in the preflight report.",
    )
    parser.add_argument(
        "--dependency-wait-seconds",
        type=int,
        default=20,
        help="Seconds to wait for locally started dependency ports before running upgrade checks.",
    )
    args = parser.parse_args()

    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        print(
            "找不到 .venv/bin/python，請先執行 "
            "python3 scripts/bootstrap_python_runtime.py --apply 建立虛擬環境，"
            "或依 README 手動建立。"
        )
        return 1

    RUN_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

    dependency_status = None
    dependency_wait_status = {}
    local_dependency_env = {}
    if args.start_dependencies:
        local_dependency_env = apply_local_dependency_env_defaults(
            enable_browser_render=True,
            prefer_browserless=True,
            prefer_unlocker=bool(args.prefer_unlocker),
        )
        dependency_status = start_dependency_services(
            ROOT,
            allow_pull_missing_images=bool(args.pull_missing_dependencies),
            include_unlocker=bool(args.prefer_unlocker),
        )
        dependency_wait_status = wait_for_local_dependency_ports(
            dependency_status,
            local_dependency_env,
            timeout_seconds=max(0, int(args.dependency_wait_seconds)),
        )
        switch_status = fallback_local_browser_render_to_playwright(
            local_dependency_env,
            dependency_status,
            dependency_wait_status,
        )
        if switch_status:
            dependency_wait_status["browser_render_fallback"] = switch_status

    migration_status = run_startup_migrations(ROOT, python, skip=bool(args.skip_migrations))
    if migration_status.get("status") == "失敗":
        print("")
        print("資料庫 migration：失敗")
        print(f"- {migration_status['message']}")
        return 1

    if not args.skip_upgrade_check:
        print_upgrade_capability_preflight(
            ROOT,
            python,
            local_dependency_env=local_dependency_env,
            strict_external=bool(args.strict_upgrade_check),
        )

    api_started = ensure_process(
        name="api",
        port=API_PORT,
        command=[
            str(python),
            "-m",
            "uvicorn",
            "app.api.main:app",
            "--host",
            API_HOST,
            "--port",
            str(API_PORT),
        ],
        log_path=LOG_DIR / "api.log",
    )
    streamlit_started = ensure_process(
        name="streamlit",
        port=STREAMLIT_PORT,
        command=[
            str(python),
            "-m",
            "streamlit",
            "run",
            "streamlit_app.py",
            "--server.address",
            STREAMLIT_HOST,
            "--server.port",
            str(STREAMLIT_PORT),
            "--server.headless",
            "true",
        ],
        log_path=LOG_DIR / "streamlit.log",
    )
    schedule_config = ScheduleConfigStore().load()
    celery_started = False
    celery_enabled = bool(schedule_config.enabled)
    if celery_enabled:
        celery_started = ensure_background_process(
            name="celery",
            command=[
                str(python),
                "-m",
                "celery",
                "-A",
                "app.tasks.celery_app.celery_app",
                "worker",
                "-B",
                "--loglevel=INFO",
                "--pool=solo",
            ],
            log_path=LOG_DIR / "celery.log",
        )

    api_ok = wait_for_http(f"http://{API_HOST}:{API_PORT}/health", timeout_seconds=30)
    streamlit_ok = wait_for_port("127.0.0.1", STREAMLIT_PORT, timeout_seconds=30)
    local_url = f"http://127.0.0.1:{STREAMLIT_PORT}"
    lan_ip = local_lan_ip()
    lan_url = f"http://{lan_ip}:{STREAMLIT_PORT}" if lan_ip else None

    print("")
    print("啟動結果")
    if dependency_status:
        print(
            "- 依賴服務："
            f"{dependency_status['status']}，"
            f"{dependency_status['message']}"
        )
        for line in dependency_wait_status_lines(dependency_wait_status):
            print(line)
    print(f"- 資料庫 migration：{migration_status['status']}，{migration_status['message']}")
    print(f"- API: {'已啟動' if api_started else '已在執行'}，健康檢查：{'正常' if api_ok else '尚未回應'}")
    print(f"- Streamlit: {'已啟動' if streamlit_started else '已在執行'}，連線檢查：{'正常' if streamlit_ok else '尚未回應'}")
    if celery_enabled:
        print(
            "- 自動排程："
            f"{'已啟動' if celery_started else '已在執行'}，"
            f"每日 {schedule_config.timezone} {schedule_config.hour:02d}:{schedule_config.minute:02d} "
            f"{schedule_config.task}"
        )
    else:
        print("- 自動排程：未啟用")
    print("")
    print("可用網址")
    print(f"- 本機：{local_url}")
    if lan_url:
        print(f"- 手機/同網路：{lan_url}")
    print("")
    print("Log 檔")
    print(f"- API: {LOG_DIR / 'api.log'}")
    print(f"- Streamlit: {LOG_DIR / 'streamlit.log'}")
    if celery_enabled:
        print(f"- Celery: {LOG_DIR / 'celery.log'}")

    if args.open_browser and streamlit_ok:
        webbrowser.open(local_url)

    return 0 if api_ok and streamlit_ok else 2


def print_upgrade_capability_preflight(
    root: Path,
    python: Path,
    local_dependency_env: dict[str, str] | None = None,
    *,
    strict_external: bool = False,
) -> None:
    try:
        service_status = importlib.import_module("app.services.service_status").service_status
        status = service_status()
        matrix = status.get("upgrade_capability_matrix") or {}
        audit = audit_upgrade_capabilities(status, strict_external=strict_external)
    except Exception as exc:
        print("")
        print("升級能力檢查：無法讀取")
        print(f"- 原因：{exc}")
        return

    advice = upgrade_dependency_advice(matrix, python=python, root=root)
    failure_capabilities = {item.get("capability") for item in audit.get("failures") or []}
    warning_capabilities = {item.get("capability") for item in audit.get("warnings") or []}
    failure_advice = [item for item in advice if item["capability"] in failure_capabilities]
    warning_advice = [item for item in advice if item["capability"] in warning_capabilities]
    summary = audit.get("summary") or {}
    implementation = audit.get("implementation") or {}
    deployment = audit.get("deployment") or {}
    print("")
    print("升級能力檢查")
    if local_dependency_env:
        applied = "、".join(sorted(local_dependency_env))
        print(f"- 本機依賴預設：已套用 {applied}（只影響本次一鍵啟動程序，不改寫 .env）。")
    print(
        "- 稽核模式："
        f"{'正式部署' if strict_external else '一般'}；"
        f"狀態 {audit.get('overall_status')}；"
        f"通過 {summary.get('ready', 0)}/{summary.get('total_checks', 0)}，"
        f"注意 {summary.get('warnings', 0)}，需處理 {summary.get('failures', 0)}。"
    )
    print(
        "- 狀態拆解："
        f"核心升級 {implementation.get('status', 'unknown')} "
        f"({implementation.get('ready', 0)}/{implementation.get('total_checks', 0)} 通過)；"
        f"外部整合 {deployment.get('status', 'unknown')} "
        f"({deployment.get('ready', 0)}/{deployment.get('total_checks', 0)} 通過)。"
    )
    if not failure_advice and not warning_advice:
        print("- AI/RAG、架構與資料可靠性能力目前沒有偵測到需處理項目。")
        return
    if failure_advice:
        print("- 必須處理：")
    for item in failure_advice:
        print(f"- {item['capability']}：{item['status']}，{item['reason']}")
        print(f"  建議：{item['action']}")
    if warning_advice:
        print("- 選配或部署注意：")
    for item in warning_advice:
        print(f"- {item['capability']}：{item['status']}，{item['reason']}")
        print(f"  建議：{item['action']}")


def run_startup_migrations(root: Path, python: Path, *, skip: bool = False) -> dict[str, str]:
    if skip:
        return {"status": "略過", "message": "使用 --skip-migrations，假設外部流程已完成。"}
    mode = startup_database_init_mode()
    normalized_mode = mode.strip().lower().replace("-", "_")
    if normalized_mode in {"none", "off", "disabled"}:
        return {"status": "略過", "message": f"DATABASE_INIT_MODE={mode}。"}
    if normalized_mode in {"create_all", "createall", "metadata"}:
        return {"status": "略過", "message": f"DATABASE_INIT_MODE={mode}，使用本機 create_all 模式。"}
    if normalized_mode not in {"alembic", "migration", "migrations"}:
        return {"status": "失敗", "message": f"不支援 DATABASE_INIT_MODE={mode}；請使用 alembic、create_all 或 none。"}
    try:
        completed = subprocess.run(
            [str(python), "-m", "alembic", "upgrade", "head"],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"status": "失敗", "message": "alembic upgrade head 逾時；請確認資料庫連線。"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "失敗", "message": f"alembic upgrade head 無法執行：{exc}"}
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "Alembic migration failed").strip()
        return {"status": "失敗", "message": message.splitlines()[-1] if message else "Alembic migration failed"}
    return {"status": "完成", "message": "已執行 alembic upgrade head。"}


def startup_database_init_mode() -> str:
    env_mode = os.environ.get("DATABASE_INIT_MODE")
    if env_mode:
        return env_mode
    try:
        settings = importlib.import_module("app.core.config").get_settings()
        return str(getattr(settings, "database_init_mode", "alembic") or "alembic")
    except Exception:
        return "alembic"


def start_dependency_services(
    root: Path,
    *,
    allow_pull_missing_images: bool = False,
    include_unlocker: bool = False,
) -> dict:
    compose_path = root / "docker-compose.yml"
    if not compose_path.exists():
        return {"status": "略過", "message": "找不到 docker-compose.yml。"}
    docker_command = docker_compose_command()
    if not docker_command:
        return {"status": "略過", "message": "找不到 Docker Compose；請先啟動 Docker Desktop。"}
    dependency_services = _dependency_services(include_unlocker=include_unlocker)
    image_status = local_docker_image_status(_dependency_images(include_unlocker=include_unlocker))
    if not image_status.get("all_present") and not allow_pull_missing_images:
        missing = "、".join(image_status.get("missing_services") or [])
        remediation = image_status.get("remediation") or "docker compose pull neo4j browserless"
        return {
            "status": "需下載",
            "message": (
                f"缺少 Docker image：{missing}。"
                f"請先執行 {remediation}，或加 --pull-missing-dependencies 允許一鍵啟動自動下載。"
            ),
        }
    if not image_status.get("all_present"):
        pull_status = pull_missing_dependency_images(
            root,
            docker_command,
            image_status.get("missing_services") or [],
        )
        if pull_status.get("status") != "已下載":
            return pull_status
        image_status = local_docker_image_status(_dependency_images(include_unlocker=include_unlocker))
        if not image_status.get("all_present"):
            missing = "、".join(image_status.get("missing_services") or [])
            return {
                "status": "失敗",
                "message": f"Docker image 下載後仍缺少：{missing}。請檢查 Docker Desktop 網路或手動重試 pull。",
            }
    profile_args = ["--profile", "unlocker"] if include_unlocker else []
    command = [
        *docker_command,
        "-f",
        str(compose_path),
        *profile_args,
        "up",
        "-d",
        *dependency_services,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "失敗",
            "message": (
                "Docker Compose 啟動逾時，可能正在下載 Neo4j/Browserless/FlareSolverr image。"
                "請確認 Docker Desktop 網路狀態，或先執行 "
                + "docker compose pull "
                + " ".join(service for service in dependency_services if service in {"neo4j", "browserless", "flaresolverr"})
                + " 後重試。"
            ),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "失敗", "message": f"Docker Compose 啟動失敗：{exc}"}
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "Docker Compose 回傳錯誤").strip()
        return {"status": "失敗", "message": message.splitlines()[-1] if message else "Docker Compose 回傳錯誤。"}
    service_label = "、".join(_dependency_service_labels(dependency_services))
    return {
        "status": "已啟動",
        "message": f"{service_label} 已送出啟動指令。",
        "services": dependency_services,
    }


def _dependency_services(*, include_unlocker: bool = False) -> list[str]:
    services = ["redis", "postgres", "neo4j", "browserless"]
    if include_unlocker:
        services.append("flaresolverr")
    return services


def _dependency_service_labels(services: list[str]) -> list[str]:
    labels = {
        "redis": "Redis",
        "postgres": "Postgres",
        "neo4j": "Neo4j",
        "browserless": "Browserless",
        "flaresolverr": "FlareSolverr",
    }
    return [labels.get(service, service) for service in services]


def _dependency_images(*, include_unlocker: bool = False) -> dict[str, str]:
    images = {
        "neo4j": "neo4j:5-community",
        "browserless": "ghcr.io/browserless/chromium:latest",
    }
    if include_unlocker:
        images["flaresolverr"] = LOCAL_FLARESOLVERR_IMAGE
    return images


def pull_missing_dependency_images(
    root: Path,
    docker_command: list[str],
    missing_services: list[str],
    *,
    timeout_seconds: int = 300,
) -> dict[str, str]:
    services = [
        service
        for service in missing_services
        if service in {"neo4j", "browserless", "flaresolverr"}
    ]
    if not services:
        return {"status": "已下載", "message": "沒有需要下載的 Docker image。"}
    for service in services:
        command = [*docker_command, "pull", service]
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                check=False,
                text=True,
                capture_output=True,
                timeout=max(30, int(timeout_seconds)),
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "失敗",
                "message": (
                    f"Docker image 下載逾時：{service}。"
                    "請確認 Docker Desktop 網路狀態，或手動執行 docker compose pull "
                    + " ".join(services)
                    + " 後重試。"
                ),
            }
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "失敗", "message": f"Docker image 下載失敗：{service}；{exc}"}
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Docker Compose pull 回傳錯誤").strip()
            return {
                "status": "失敗",
                "message": f"Docker image 下載失敗：{service}；{message.splitlines()[-1] if message else '未知錯誤'}",
            }
    return {
        "status": "已下載",
        "message": "已下載缺少的 Docker image：" + "、".join(services),
    }


def apply_local_dependency_env_defaults(
    *,
    enable_browser_render: bool = False,
    prefer_browserless: bool = False,
    prefer_unlocker: bool = False,
) -> dict[str, str]:
    applied = {}
    for key, value in LOCAL_NEO4J_ENV_DEFAULTS.items():
        if os.environ.get(key):
            continue
        os.environ[key] = value
        applied[key] = value
    if enable_browser_render:
        applied.update(
            apply_local_browser_render_env_defaults(
                prefer_browserless=prefer_browserless,
                prefer_unlocker=prefer_unlocker,
            )
        )
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


def wait_for_local_dependency_ports(
    dependency_status: dict | None,
    local_dependency_env: dict[str, str],
    *,
    timeout_seconds: int,
) -> dict[str, bool]:
    if not dependency_status or dependency_status.get("status") != "已啟動":
        return {}
    results: dict[str, bool] = {}
    neo4j_uri = str(local_dependency_env.get("NEO4J_URI") or os.environ.get("NEO4J_URI") or "")
    if _is_local_neo4j_uri(neo4j_uri):
        results["neo4j"] = wait_for_port("127.0.0.1", 7687, timeout_seconds=timeout_seconds)
    browser_render_url = str(
        local_dependency_env.get("COMPANY_FILING_BROWSER_RENDER_URL")
        or os.environ.get("COMPANY_FILING_BROWSER_RENDER_URL")
        or ""
    )
    services = set(dependency_status.get("services") or [])
    if "browserless" in services or _is_local_browserless_render_url(browser_render_url):
        results["browserless"] = wait_for_port(
            "127.0.0.1",
            LOCAL_BROWSERLESS_PORT,
            timeout_seconds=timeout_seconds,
        )
    if "flaresolverr" in services or _is_local_flaresolverr_render_url(browser_render_url):
        results["flaresolverr"] = wait_for_port(
            "127.0.0.1",
            LOCAL_FLARESOLVERR_PORT,
            timeout_seconds=timeout_seconds,
        )
    return results


def fallback_local_browser_render_to_playwright(
    local_dependency_env: dict[str, str],
    dependency_status: dict | None,
    dependency_wait_status: dict[str, bool],
) -> dict[str, str]:
    browserless_url = LOCAL_BROWSER_RENDER_ENV_DEFAULTS["COMPANY_FILING_BROWSER_RENDER_URL"]
    flaresolverr_url = LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS["COMPANY_FILING_BROWSER_RENDER_URL"]
    current_url = local_dependency_env.get("COMPANY_FILING_BROWSER_RENDER_URL")
    if current_url not in {browserless_url, flaresolverr_url}:
        return {}
    selected_browserless = current_url == browserless_url
    selected_flaresolverr = current_url == flaresolverr_url
    render_ready = (
        dependency_status is not None
        and dependency_status.get("status") == "已啟動"
        and (
            (selected_browserless and dependency_wait_status.get("browserless") is True)
            or (selected_flaresolverr and dependency_wait_status.get("flaresolverr") is True)
        )
    )
    if render_ready:
        return {}
    if selected_flaresolverr and dependency_wait_status.get("browserless") is True:
        for key, value in LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS.items():
            if os.environ.get(key) == value:
                os.environ.pop(key, None)
            local_dependency_env.pop(key, None)
        for key, value in LOCAL_BROWSER_RENDER_ENV_DEFAULTS.items():
            os.environ[key] = value
            local_dependency_env[key] = value
        return {
            "status": "switched_to_browserless",
            "reason": "flaresolverr_not_ready",
            "provider": "browserless",
        }
    if os.environ.get("COMPANY_FILING_PROXY_URLS"):
        return {}
    if os.environ.get("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"):
        return {}
    runtime = company_filing_playwright_browser_status()
    if not runtime.get("browser_available"):
        return {}
    selected_defaults = (
        LOCAL_FLARESOLVERR_RENDER_ENV_DEFAULTS if selected_flaresolverr else LOCAL_BROWSER_RENDER_ENV_DEFAULTS
    )
    for key, value in selected_defaults.items():
        if os.environ.get(key) == value:
            os.environ.pop(key, None)
        local_dependency_env.pop(key, None)
    os.environ["COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"] = "true"
    local_dependency_env["COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"] = "true"
    return {
        "status": "switched_to_playwright",
        "reason": "flaresolverr_not_ready" if selected_flaresolverr else "browserless_not_ready",
        "browser": str(runtime.get("browser") or "chromium"),
    }


def dependency_wait_status_lines(wait_status: dict) -> list[str]:
    if not wait_status:
        return []
    labels = {
        "neo4j": "Neo4j 7687",
        "browserless": "Browserless 3000",
        "flaresolverr": "FlareSolverr 8191",
    }
    lines = []
    for service, ready in sorted(wait_status.items()):
        if isinstance(ready, bool):
            lines.append(f"- {labels.get(service, service)}：{'就緒' if ready else '尚未就緒'}")
        else:
            status = ready.get("status") if isinstance(ready, dict) else ready
            lines.append(f"- {labels.get(service, service)}：{status}")
    bool_values = [ready for ready in wait_status.values() if isinstance(ready, bool)]
    if any(not ready for ready in bool_values):
        lines.append(
            "- 依賴服務尚未就緒時，可稍後重跑或檢查 "
            "docker compose ps / docker compose logs neo4j / docker compose logs browserless / "
            "docker compose logs flaresolverr；"
            "若 image 下載卡住，可先執行 docker compose pull neo4j browserless flaresolverr。"
        )
    return lines


def _is_local_neo4j_uri(uri: str) -> bool:
    return uri.startswith(("neo4j://localhost:", "neo4j://127.0.0.1:", "bolt://localhost:", "bolt://127.0.0.1:"))


def _is_local_browserless_render_url(url: str) -> bool:
    return str(url or "").startswith(
        (
            f"http://localhost:{LOCAL_BROWSERLESS_PORT}/",
            f"http://127.0.0.1:{LOCAL_BROWSERLESS_PORT}/",
        )
    )


def _is_local_flaresolverr_render_url(url: str) -> bool:
    return str(url or "").startswith(
        (
            f"http://localhost:{LOCAL_FLARESOLVERR_PORT}/",
            f"http://127.0.0.1:{LOCAL_FLARESOLVERR_PORT}/",
        )
    )


def docker_compose_command() -> list[str] | None:
    for command in (["docker", "compose"], ["docker-compose"]):
        try:
            completed = subprocess.run(
                [*command, "version"],
                check=False,
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            return command
    return None


def upgrade_dependency_advice(matrix: dict, *, python: Path, root: Path) -> list[dict[str, str]]:
    python_display = _display_path(python, root)
    items: list[dict[str, str]] = []
    ai_rag = matrix.get("ai_rag") or {}
    architecture = matrix.get("architecture") or {}
    data_business_logic = matrix.get("data_business_logic") or {}

    python_runtime = architecture.get("python_runtime") or {}
    python_runtime_evidence = python_runtime.get("evidence") or {}
    if python_runtime and python_runtime.get("status") != "ready":
        minimum_supported = str(python_runtime_evidence.get("minimum_supported") or "3.11")
        current_version = str(python_runtime_evidence.get("current_version") or "unknown")
        items.append(
            {
                "capability": "python_runtime",
                "status": str(python_runtime.get("status") or "unknown"),
                "reason": f"目前 Python {current_version}，專案目標為 {minimum_supported}+",
                "action": (
                    "先執行 "
                    f"{python_display} scripts/bootstrap_python_runtime.py --apply --replace-existing；"
                    f"若尚未有支援 interpreter，可先安裝 Python {minimum_supported}+。"
                    f"手動路徑仍可用 python{minimum_supported} -m venv .venv，"
                    f"再執行 {_pip_install_action(python_display, '.[dev,pdf,visual,browser,graph]')}"
                ),
            }
        )

    embedding = ai_rag.get("multilingual_embedding") or {}
    embedding_evidence = embedding.get("evidence") or {}
    if embedding.get("status") != "ready":
        fallback = str(embedding_evidence.get("fallback_reason") or "not_ready")
        provider = str(embedding_evidence.get("provider") or "unknown")
        action = (
            _pip_install_action(python_display, ".[rag]")
            if fallback.startswith("missing_dependency")
            else "確認 RAG_EMBEDDING_PROVIDER、RAG_EMBEDDING_MODEL 與對應 API key"
        )
        items.append(
            {
                "capability": "multilingual_embedding",
                "status": str(embedding.get("status") or "unknown"),
                "reason": f"{provider} 尚未啟用（{fallback}）",
                "action": action,
            }
        )

    llm = ai_rag.get("llm_sdk_and_fallback") or {}
    llm_evidence = llm.get("evidence") or {}
    if llm.get("status") != "ready":
        dependency = str(llm_evidence.get("dependency") or "LLM SDK")
        dependency_available = llm_evidence.get("dependency_available")
        action = (
            _pip_install_action(python_display, ".")
            if dependency_available is False
            else "設定 GOOGLE_API_KEYS / OPENAI_API_KEY / ANTHROPIC_API_KEY 與 LLM_FALLBACK_MODELS"
        )
        items.append(
            {
                "capability": "llm_sdk_and_fallback",
                "status": str(llm.get("status") or "unknown"),
                "reason": f"{dependency} dependency_available={dependency_available}",
                "action": action,
            }
        )

    quota_routing = ai_rag.get("llm_quota_routing") or {}
    quota_evidence = quota_routing.get("evidence") or {}
    if quota_routing and quota_routing.get("status") != "ready":
        failed_checks = quota_evidence.get("failed_checks") or ["quota_routing_not_ready"]
        items.append(
            {
                "capability": "llm_quota_routing",
                "status": str(quota_routing.get("status") or "unknown"),
                "reason": "、".join(str(check) for check in failed_checks),
                "action": (
                    "設定 PRIMARY_LLM_MODEL=gemini-3.5-flash，"
                    "LLM_FALLBACK_MODELS=gemini-2.5-flash,gemini-3.1-flash-lite,"
                    "gemini-2.5-flash-lite,gemma-4-31b-it，"
                    "LLM_QUOTA_HARD_ROUTING_ENABLED=true，"
                    "LLM_MODEL_QUOTA_COOLDOWN_SECONDS=3600，並用 "
                    "LLM_MODEL_DAILY_REQUEST_BUDGETS 維護 Flash 同級額度與 Gemma 高額度保底"
                ),
            }
        )

    reranking = ai_rag.get("reranking") or {}
    reranking_evidence = reranking.get("evidence") or {}
    if reranking and reranking.get("status") != "ready":
        provider = str(reranking_evidence.get("provider") or "unknown")
        execution_mode = str(reranking_evidence.get("execution_mode") or "unknown")
        model_gap = str(
            reranking_evidence.get("model_reranker_gap")
            or reranking_evidence.get("fallback_reason")
            or "model_reranker_not_ready"
        )
        dependency_available = reranking_evidence.get("dependency_available")
        api_key_configured = reranking_evidence.get("api_key_configured")
        if dependency_available is False:
            action = _pip_install_action(python_display, ".[rag]")
        elif api_key_configured is False:
            action = "設定 COHERE_API_KEY，或改用 RAG_RERANKER_PROVIDER=bge 並安裝 .[rag]"
        elif reranking_evidence.get("keyword_fallback") or execution_mode == "keyword":
            action = (
                '設定 RAG_RERANKER_PROVIDER=bge 並執行 '
                f'{_pip_install_action(python_display, ".[rag]")}；'
                "或設定 RAG_RERANKER_PROVIDER=cohere、RAG_RERANKER_MODEL=rerank-v3.5 與 COHERE_API_KEY"
            )
        else:
            action = "確認 RAG_RERANKER_PROVIDER、RAG_RERANKER_MODEL 與模型/API 可用性"
        items.append(
            {
                "capability": "reranking",
                "status": str(reranking.get("status") or "unknown"),
                "reason": f"{provider} execution_mode={execution_mode}（{model_gap}）",
                "action": action,
            }
        )

    visual_rag = ai_rag.get("visual_rag") or {}
    visual_rag_evidence = visual_rag.get("evidence") or {}
    if visual_rag and visual_rag.get("status") != "ready":
        runtime = visual_rag_evidence.get("runtime") or {}
        fallback = str(runtime.get("fallback_reason") or "visual_rag_not_configured")
        actions = []
        if not visual_rag_evidence.get("enabled"):
            actions.append("設定 COMPANY_FILING_VISUAL_RAG_ENABLED=true")
        if visual_rag_evidence.get("renderer_dependency_available") is False:
            actions.append(_pip_install_action(python_display, ".[visual]"))
        if not (runtime.get("vision_model_key_configured") or visual_rag_evidence.get("runtime_available")):
            actions.append(
                "設定 COMPANY_FILING_VISUAL_RAG_MODEL 與 GOOGLE_API_KEYS / OPENAI_API_KEY / ANTHROPIC_API_KEY"
            )
        items.append(
            {
                "capability": "visual_rag",
                "status": str(visual_rag.get("status") or "unknown"),
                "reason": fallback,
                "action": "；".join(actions) if actions else "確認 Visual RAG renderer 與 vision LLM 設定",
            }
        )

    neo4j = ai_rag.get("neo4j_import") or {}
    neo4j_evidence = neo4j.get("evidence") or {}
    if neo4j.get("status") != "ready":
        fallback = str(neo4j_evidence.get("fallback_reason") or "not_configured")
        dependency_available = neo4j_evidence.get("dependency_available")
        if dependency_available is False:
            action = (
                f'{_pip_install_action(python_display, ".[graph]")}，並設定 '
                "NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD"
            )
        elif fallback.startswith("connection_failed"):
            action = (
                "Neo4j 已設定但連線失敗；確認帳密、7687 連線埠與服務狀態。"
                "本機可先執行 docker compose up -d neo4j，或用 start_system.py --start-dependencies"
            )
        else:
            action = (
                "設定 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD；"
                "本機可先執行 docker compose up -d neo4j，或用 start_system.py --start-dependencies"
            )
        items.append(
            {
                "capability": "neo4j_import",
                "status": str(neo4j.get("status") or "unknown"),
                "reason": fallback,
                "action": action,
            }
        )

    live_cypher = ai_rag.get("graphrag_live_cypher_query") or {}
    live_cypher_evidence = live_cypher.get("evidence") or {}
    if live_cypher and live_cypher.get("status") != "ready":
        items.append(
            {
                "capability": "graphrag_live_cypher_query",
                "status": str(live_cypher.get("status") or "unknown"),
                "reason": (
                    f"Neo4j ready={live_cypher_evidence.get('neo4j_ready')}；"
                    f"planner enabled={live_cypher_evidence.get('planner_enabled')}"
                ),
                "action": (
                    "啟動 Neo4j 並設定 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD；"
                    "本機可用 docker compose up -d neo4j 或 start_system.py --start-dependencies，"
                    "再用 /supply-chain/graph/cypher-query 驗證 guarded read-only 查詢"
                ),
            }
        )

    market_fallback = data_business_logic.get("market_data_provider_fallback") or {}
    market_fallback_evidence = market_fallback.get("evidence") or {}
    if market_fallback.get("status") != "ready":
        reason = str(market_fallback_evidence.get("fallback_reason") or "market_provider_not_ready")
        actions = []
        if market_fallback_evidence.get("official_openapi_fallback_enabled"):
            actions.append("官方 OpenAPI 最新資料 fallback 已啟用，但完整歷史財務與完整股價歷史仍需授權來源")
        if not market_fallback_evidence.get("finmind_authenticated"):
            actions.append("設定 FINMIND_TOKEN，讓月營收、五年財務與估值使用穩定授權來源")
        if not market_fallback_evidence.get("fugle_price_fallback_configured"):
            actions.append("設定 FUGLE_API_KEY，讓股價歷史在 FinMind 失敗時可切到 Fugle")
        if not actions:
            actions.append("確認 MARKET_PRICE_PROVIDER_ORDER=finmind,fugle 與市場資料 API key")
        items.append(
            {
                "capability": "market_data_provider_fallback",
                "status": str(market_fallback.get("status") or "unknown"),
                "reason": reason,
                "action": "；".join(actions),
            }
        )

    filing_fallback = data_business_logic.get("company_filing_browser_or_proxy_fallback") or {}
    filing_fallback_evidence = filing_fallback.get("evidence") or {}
    if filing_fallback.get("status") not in {None, "ready"}:
        actions = [
            "設定 COMPANY_FILING_PROXY_URLS 讓重試時可切換代理",
            "或設定 COMPANY_FILING_BROWSER_RENDER_ENABLED=true、COMPANY_FILING_BROWSER_RENDER_PROVIDER 與 COMPANY_FILING_BROWSER_RENDER_URL",
        ]
        if filing_fallback_evidence.get("playwright_render_dependency_available"):
            actions.append("或啟用 COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=true 做本機瀏覽器渲染")
        else:
            actions.append(f'若要用本機 Playwright，先執行 {_pip_install_action(python_display, ".[browser]")}')
        items.append(
            {
                "capability": "company_filing_browser_or_proxy_fallback",
                "status": str(filing_fallback.get("status") or "unknown"),
                "reason": "公司文件 Proxy / Browser render / Playwright 後援尚未設定",
                "action": "；".join(actions),
            }
        )

    structured_api = data_business_logic.get("company_filing_structured_api_fallback") or {}
    structured_evidence = structured_api.get("evidence") or {}
    if structured_api.get("status") not in {None, "ready"}:
        items.append(
            {
                "capability": "company_filing_structured_api_fallback",
                "status": str(structured_api.get("status") or "unknown"),
                "reason": str(
                    (structured_evidence.get("runtime") or {}).get("fallback_reason")
                    or "structured_company_filing_api_not_configured"
                ),
                "action": (
                    "若法說會簡報或重大訊息常被擋，設定 "
                    "COMPANY_FILING_STRUCTURED_API_PROVIDER、COMPANY_FILING_STRUCTURED_API_URL "
                    "與 COMPANY_FILING_STRUCTURED_API_TOKEN 串接 TEJ 或專業資料 API；"
                    "設定後執行 .venv/bin/python scripts/structured_company_filing_smoke.py "
                    "--ticker 2330 --company-name 台積電 --document-type investor_presentation --json"
                ),
            }
        )

    migrations = architecture.get("database_migrations") or {}
    migration_evidence = migrations.get("evidence") or {}
    if migration_evidence.get("up_to_date") is False:
        if (
            migration_evidence.get("version_table_present") is False
            and migration_evidence.get("head_revision")
            and not migration_evidence.get("current_revision")
        ):
            migration_action = f"{python_display} -m alembic stamp head"
            migration_reason = "既有 schema 尚未標記 Alembic 版本"
        else:
            migration_action = f"{python_display} -m alembic upgrade head"
            migration_reason = "資料庫尚未升級到 Alembic head"
        items.append(
            {
                "capability": "database_migrations",
                "status": str(migrations.get("status") or "unknown"),
                "reason": migration_reason,
                "action": migration_action,
            }
        )

    return items


def _pip_install_action(python_display: str, target: str) -> str:
    return (
        f"{python_display} -m pip install --upgrade pip setuptools && "
        f'{python_display} -m pip install -e "{target}"'
    )


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def ensure_process(name: str, port: int, command: list[str], log_path: Path) -> bool:
    if is_port_open("127.0.0.1", port):
        return False

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (RUN_DIR / f"{name}.pid").write_text(str(process.pid), encoding="utf-8")
    return True


def ensure_background_process(name: str, command: list[str], log_path: Path) -> bool:
    pid_path = RUN_DIR / f"{name}.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = 0
        if pid and is_process_running(pid):
            return False

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return True


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_http(url: str, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    return False


def wait_for_port(host: str, port: int, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def local_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            return ip if not ip.startswith("127.") else None
    except OSError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
