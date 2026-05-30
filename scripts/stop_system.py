from __future__ import annotations

import os
import signal
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / ".run"


def main() -> int:
    stopped = []
    missing = []
    for name in ["streamlit", "api"]:
        pid_path = RUN_DIR / f"{name}.pid"
        if not pid_path.exists():
            missing.append(name)
            continue
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid_path.unlink(missing_ok=True)
            missing.append(name)
            continue
        if stop_pid(pid):
            stopped.append(name)
        else:
            missing.append(name)
        pid_path.unlink(missing_ok=True)

    print("停止結果")
    print("- 已停止：" + ("、".join(stopped) if stopped else "無"))
    print("- 未找到：" + ("、".join(missing) if missing else "無"))
    return 0


def stop_pid(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return True
    return True


if __name__ == "__main__":
    raise SystemExit(main())
