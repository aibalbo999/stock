from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app.services.maintenance_diagnostic_actions import (
    MAINTENANCE_DIAGNOSTIC_ACTIONS,
    maintenance_diagnostic_action_row,
    maintenance_diagnostic_action_safe_to_run,
)
from app.services.maintenance_diagnostic_summaries import (
    diagnostic_summary_rows as build_diagnostic_summary_rows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_OUTPUT_CHARS = 4000


def maintenance_diagnostic_action_catalog() -> dict:
    return {
        "collector_path": "app/services/maintenance_diagnostics.py",
        "execution_policy": "allowlisted_safe_diagnostic_subprocess",
        "actions": [
            maintenance_diagnostic_action_row(action)
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
    if not maintenance_diagnostic_action_safe_to_run(action):
        raise ValueError(f"Maintenance diagnostic action is not allowlisted safe: {action_id}")
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
            **maintenance_diagnostic_action_row(action),
            "status": "timeout",
            "returncode": None,
            "duration_seconds": round(elapsed, 3),
            "summary_rows": build_diagnostic_summary_rows(str(action["id"]), exc.stdout),
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
            "message": f"診斷逾時：{int(action['timeout_seconds'])}s",
        }
    elapsed = time.monotonic() - started_at
    return {
        **maintenance_diagnostic_action_row(action),
        "status": "success" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "duration_seconds": round(elapsed, 3),
        "summary_rows": build_diagnostic_summary_rows(str(action["id"]), completed.stdout),
        "stdout_tail": _tail_text(completed.stdout),
        "stderr_tail": _tail_text(completed.stderr),
        "message": "診斷完成" if completed.returncode == 0 else "診斷回傳非 0 結束碼",
    }


def _tail_text(value: object) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-MAX_OUTPUT_CHARS:]
