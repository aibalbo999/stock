from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / ".run"
LOG_DIR = ROOT / "logs"
API_HOST = "127.0.0.1"
API_PORT = 8000
STREAMLIT_HOST = "0.0.0.0"
STREAMLIT_PORT = 8501


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the stock analysis system.")
    parser.add_argument("--open-browser", action="store_true", help="Open Streamlit in the default browser.")
    args = parser.parse_args()

    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        print("找不到 .venv/bin/python，請先依 README 建立虛擬環境並安裝依賴。")
        return 1

    RUN_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

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
