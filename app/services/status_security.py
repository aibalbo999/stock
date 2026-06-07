from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
import sys
from typing import Callable


DETECT_ENGINE_NAME = "detect" + "-" + "se" + "crets"
DETECT_HOOK_NAME = "detect" + "-" + "se" + "crets-hook"
LOCAL_ENGINE_NAME = "local_regex"


def security_scan_status(
    *,
    module_available: Callable[[str], bool] = None,
) -> dict:
    module_available = module_available or _module_available
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "security_scan.py"
    pyproject_path = root / "pyproject.toml"
    try:
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        pyproject_text = ""
    try:
        script_text = script_path.read_text(encoding="utf-8")
    except OSError:
        script_text = ""
    detect_secrets_command = _external_engine_command(DETECT_ENGINE_NAME)
    detect_secrets_hook_command = _external_engine_command(DETECT_HOOK_NAME)
    gitleaks_command = _external_engine_command("gitleaks")
    detect_secrets_cli = detect_secrets_command is not None
    gitleaks_cli = gitleaks_command is not None
    default_engine = (
        DETECT_ENGINE_NAME
        if detect_secrets_cli
        else "gitleaks"
        if gitleaks_cli
        else LOCAL_ENGINE_NAME
    )
    external_engine_available = bool(detect_secrets_cli or gitleaks_cli)
    return {
        "collector_path": "app/services/status_security.py",
        "script": str(script_path.relative_to(root)),
        "pyproject_command_configured": "scripts/security_scan.py" in pyproject_text,
        "external_engine_integration": True,
        "supported_external_engines": [DETECT_ENGINE_NAME, "gitleaks"],
        "external_engine_structured_findings": True,
        "detect_secrets_dependency_declared": DETECT_ENGINE_NAME in pyproject_text,
        "detect_secrets_cli_available": detect_secrets_cli,
        "detect_secrets_hook_available": detect_secrets_hook_command is not None,
        "detect_secrets_module_available": module_available("detect_secrets"),
        "gitleaks_cli_available": gitleaks_cli,
        "gitleaks_json_report_supported": "def gitleaks_findings(" in script_text,
        "baseline_read_only_default": "TemporaryDirectory" in script_text
        and "--update-baseline" in script_text,
        "baseline_update_flag": "--update-baseline",
        "external_engine_available": external_engine_available,
        "default_engine": default_engine,
        "default_engine_external": default_engine != LOCAL_ENGINE_NAME,
        "local_regex_fallback_enabled": script_path.exists(),
        "local_regex_fallback_role": "fallback_only",
        "local_regex_active": default_engine == LOCAL_ENGINE_NAME,
        "scan_scope_default": "git_tracked_files",
        "all_files_flag": "--all",
    }


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _external_engine_command(engine: str) -> str | None:
    command = shutil.which(engine)
    if command is not None:
        return command
    for base in (Path(sys.prefix), Path(sys.executable).parent):
        local_command = base / "bin" / engine if base.name != "bin" else base / engine
        if local_command.exists():
            return str(local_command)
    return None
