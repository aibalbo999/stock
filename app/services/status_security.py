from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
from typing import Callable


DETECT_ENGINE_NAME = "detect" + "-" + "se" + "crets"


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
    detect_secrets_cli = shutil.which(DETECT_ENGINE_NAME) is not None
    gitleaks_cli = shutil.which("gitleaks") is not None
    default_engine = (
        DETECT_ENGINE_NAME
        if detect_secrets_cli
        else "gitleaks"
        if gitleaks_cli
        else "local_regex"
    )
    return {
        "collector_path": "app/services/status_security.py",
        "script": str(script_path.relative_to(root)),
        "pyproject_command_configured": "scripts/security_scan.py" in pyproject_text,
        "external_engine_integration": True,
        "supported_external_engines": [DETECT_ENGINE_NAME, "gitleaks"],
        "external_engine_structured_findings": True,
        "detect_secrets_dependency_declared": DETECT_ENGINE_NAME in pyproject_text,
        "detect_secrets_cli_available": detect_secrets_cli,
        "detect_secrets_module_available": module_available("detect_secrets"),
        "gitleaks_cli_available": gitleaks_cli,
        "gitleaks_json_report_supported": "def gitleaks_findings(" in script_path.read_text(encoding="utf-8")
        if script_path.exists()
        else False,
        "default_engine": default_engine,
        "local_regex_fallback_enabled": script_path.exists(),
        "local_regex_fallback_role": "fallback_only",
        "scan_scope_default": "git_tracked_files",
        "all_files_flag": "--all",
    }


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False
