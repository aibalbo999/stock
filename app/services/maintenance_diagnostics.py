from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_OUTPUT_CHARS = 4000
MAINTENANCE_DIAGNOSTIC_ACTIONS = {
    "upgrade_audit": {
        "id": "upgrade_audit",
        "label": "Upgrade audit",
        "description": "檢查核心升級能力與外部部署選配狀態。",
        "display_command": ".venv/bin/python scripts/upgrade_audit.py",
        "argv": [sys.executable, "scripts/upgrade_audit.py"],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "external_integrations_smoke": {
        "id": "external_integrations_smoke",
        "label": "External integrations smoke",
        "description": "執行外部整合 smoke contract，不會啟動選配服務。",
        "display_command": ".venv/bin/python scripts/external_integrations_smoke.py --json",
        "argv": [sys.executable, "scripts/external_integrations_smoke.py", "--json"],
        "timeout_seconds": 90,
        "read_only": True,
    },
    "celery_inspect_ping": {
        "id": "celery_inspect_ping",
        "label": "Celery inspect ping",
        "description": "檢查 Celery worker 是否回應目前設定的 Redis broker。",
        "display_command": (
            ".venv/bin/python -m celery -A app.tasks.celery_app.celery_app inspect ping"
        ),
        "argv": [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.tasks.celery_app.celery_app",
            "inspect",
            "ping",
        ],
        "timeout_seconds": 20,
        "read_only": True,
    },
}


def maintenance_diagnostic_action_catalog() -> dict:
    return {
        "collector_path": "app/services/maintenance_diagnostics.py",
        "execution_policy": "allowlisted_read_only_subprocess",
        "actions": [
            _action_catalog_row(action)
            for action in sorted(
                MAINTENANCE_DIAGNOSTIC_ACTIONS.values(),
                key=lambda item: str(item["id"]),
            )
        ],
    }


def run_maintenance_diagnostic_action(action_id: str, *, root: Path | None = None) -> dict:
    action = MAINTENANCE_DIAGNOSTIC_ACTIONS.get(str(action_id or ""))
    if not action:
        raise ValueError(f"Unknown maintenance diagnostic action: {action_id}")
    if not action.get("read_only"):
        raise ValueError(f"Maintenance diagnostic action is not read-only: {action_id}")
    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            [str(part) for part in action["argv"]],
            cwd=root or PROJECT_ROOT,
            check=False,
            text=True,
            capture_output=True,
            timeout=int(action["timeout_seconds"]),
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started_at
        return {
            **_action_catalog_row(action),
            "status": "timeout",
            "returncode": None,
            "duration_seconds": round(elapsed, 3),
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
            "message": f"診斷逾時：{int(action['timeout_seconds'])}s",
        }
    elapsed = time.monotonic() - started_at
    return {
        **_action_catalog_row(action),
        "status": "success" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "duration_seconds": round(elapsed, 3),
        "stdout_tail": _tail_text(completed.stdout),
        "stderr_tail": _tail_text(completed.stderr),
        "message": "診斷完成" if completed.returncode == 0 else "診斷回傳非 0 結束碼",
    }


def _action_catalog_row(action: dict) -> dict:
    return {
        "id": str(action["id"]),
        "label": str(action["label"]),
        "description": str(action["description"]),
        "display_command": str(action["display_command"]),
        "timeout_seconds": int(action["timeout_seconds"]),
        "read_only": bool(action["read_only"]),
    }


def _tail_text(value: object) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-MAX_OUTPUT_CHARS:]
