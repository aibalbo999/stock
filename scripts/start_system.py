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
LOCAL_BROWSER_RENDER_ENV_DEFAULTS = {
    "COMPANY_FILING_BROWSER_RENDER_ENABLED": "true",
    "COMPANY_FILING_BROWSER_RENDER_URL": (
        f"http://127.0.0.1:{LOCAL_BROWSERLESS_PORT}/content?token=stock_ai_browserless_token"
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the stock analysis system.")
    parser.add_argument("--open-browser", action="store_true", help="Open Streamlit in the default browser.")
    parser.add_argument(
        "--start-dependencies",
        action="store_true",
        help="Start docker-compose dependencies: Redis, Postgres, Neo4j, and Browserless.",
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
        print("找不到 .venv/bin/python，請先依 README 建立虛擬環境並安裝依賴。")
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
        )
        dependency_status = start_dependency_services(
            ROOT,
            allow_pull_missing_images=bool(args.pull_missing_dependencies),
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
    print(f"- API: {'已啟動' if api_started else '已在執行'}，健康檢查：{'正常' if api_ok else '尚未回應'}")
    print(f"- Streamlit: {'已啟動' if streamlit_started else '已在執行'}，連線檢查：{'正常' if streamlit_ok else '尚未回應'}")
    print("")
    print("可用網址")
    print(f"- 本機：{local_url}")
    if lan_url:
        print(f"- 手機/同網路：{lan_url}")
    print("")
    print("Log 檔")
    print(f"- API: {LOG_DIR / 'api.log'}")
    print(f"- Streamlit: {LOG_DIR / 'streamlit.log'}")

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


def start_dependency_services(root: Path, *, allow_pull_missing_images: bool = False) -> dict[str, str]:
    compose_path = root / "docker-compose.yml"
    if not compose_path.exists():
        return {"status": "略過", "message": "找不到 docker-compose.yml。"}
    docker_command = docker_compose_command()
    if not docker_command:
        return {"status": "略過", "message": "找不到 Docker Compose；請先啟動 Docker Desktop。"}
    image_status = local_docker_image_status()
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
        image_status = local_docker_image_status()
        if not image_status.get("all_present"):
            missing = "、".join(image_status.get("missing_services") or [])
            return {
                "status": "失敗",
                "message": f"Docker image 下載後仍缺少：{missing}。請檢查 Docker Desktop 網路或手動重試 pull。",
            }
    command = [
        *docker_command,
        "-f",
        str(compose_path),
        "up",
        "-d",
        "redis",
        "postgres",
        "neo4j",
        "browserless",
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
                "Docker Compose 啟動逾時，可能正在下載 Neo4j/Browserless image。"
                "請確認 Docker Desktop 網路狀態，或先執行 docker compose pull neo4j browserless 後重試。"
            ),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "失敗", "message": f"Docker Compose 啟動失敗：{exc}"}
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "Docker Compose 回傳錯誤").strip()
        return {"status": "失敗", "message": message.splitlines()[-1] if message else "Docker Compose 回傳錯誤。"}
    return {"status": "已啟動", "message": "Redis、Postgres、Neo4j、Browserless 已送出啟動指令。"}


def pull_missing_dependency_images(
    root: Path,
    docker_command: list[str],
    missing_services: list[str],
    *,
    timeout_seconds: int = 300,
) -> dict[str, str]:
    services = [service for service in missing_services if service in {"neo4j", "browserless"}]
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
) -> dict[str, str]:
    applied = {}
    for key, value in LOCAL_NEO4J_ENV_DEFAULTS.items():
        if os.environ.get(key):
            continue
        os.environ[key] = value
        applied[key] = value
    if enable_browser_render:
        applied.update(apply_local_browser_render_env_defaults(prefer_browserless=prefer_browserless))
    return applied


def apply_local_browser_render_env_defaults(*, prefer_browserless: bool = False) -> dict[str, str]:
    if os.environ.get("COMPANY_FILING_PROXY_URLS"):
        return {}
    if os.environ.get("COMPANY_FILING_BROWSER_RENDER_ENABLED") and os.environ.get(
        "COMPANY_FILING_BROWSER_RENDER_URL"
    ):
        return {}
    if os.environ.get("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"):
        return {}
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
    dependency_status: dict[str, str] | None,
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
    if _is_local_browser_render_url(browser_render_url):
        results["browserless"] = wait_for_port(
            "127.0.0.1",
            LOCAL_BROWSERLESS_PORT,
            timeout_seconds=timeout_seconds,
        )
    return results


def fallback_local_browser_render_to_playwright(
    local_dependency_env: dict[str, str],
    dependency_status: dict[str, str] | None,
    dependency_wait_status: dict[str, bool],
) -> dict[str, str]:
    default_url = LOCAL_BROWSER_RENDER_ENV_DEFAULTS["COMPANY_FILING_BROWSER_RENDER_URL"]
    if local_dependency_env.get("COMPANY_FILING_BROWSER_RENDER_URL") != default_url:
        return {}
    browserless_ready = (
        dependency_status is not None
        and dependency_status.get("status") == "已啟動"
        and dependency_wait_status.get("browserless") is True
    )
    if browserless_ready:
        return {}
    if os.environ.get("COMPANY_FILING_PROXY_URLS"):
        return {}
    if os.environ.get("COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"):
        return {}
    runtime = company_filing_playwright_browser_status()
    if not runtime.get("browser_available"):
        return {}
    for key, value in LOCAL_BROWSER_RENDER_ENV_DEFAULTS.items():
        if os.environ.get(key) == value:
            os.environ.pop(key, None)
        local_dependency_env.pop(key, None)
    os.environ["COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"] = "true"
    local_dependency_env["COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED"] = "true"
    return {
        "status": "switched_to_playwright",
        "reason": "browserless_not_ready",
        "browser": str(runtime.get("browser") or "chromium"),
    }


def dependency_wait_status_lines(wait_status: dict) -> list[str]:
    if not wait_status:
        return []
    labels = {"neo4j": "Neo4j 7687", "browserless": "Browserless 3000"}
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
            "docker compose ps / docker compose logs neo4j / docker compose logs browserless；"
            "若 image 下載卡住，可先執行 docker compose pull neo4j browserless。"
        )
    return lines


def _is_local_neo4j_uri(uri: str) -> bool:
    return uri.startswith(("neo4j://localhost:", "neo4j://127.0.0.1:", "bolt://localhost:", "bolt://127.0.0.1:"))


def _is_local_browser_render_url(url: str) -> bool:
    return str(url or "").startswith(
        (
            f"http://localhost:{LOCAL_BROWSERLESS_PORT}/",
            f"http://127.0.0.1:{LOCAL_BROWSERLESS_PORT}/",
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
            "或設定 COMPANY_FILING_BROWSER_RENDER_ENABLED=true 與 COMPANY_FILING_BROWSER_RENDER_URL",
        ]
        if filing_fallback_evidence.get("playwright_render_dependency_available"):
            actions.append("或啟用 COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED=true 做本機瀏覽器渲染")
        else:
            actions.append(f'若要用本機 Playwright，先執行 {_pip_install_action(python_display, ".[browser]")}')
        items.append(
            {
                "capability": "company_filing_browser_or_proxy_fallback",
                "status": str(filing_fallback.get("status") or "unknown"),
                "reason": "公司文件 Proxy / Browserless / Playwright 後援尚未設定",
                "action": "；".join(actions),
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
