from __future__ import annotations

from pathlib import Path
import sys


def python_runtime_status() -> dict:
    root = Path(__file__).resolve().parents[2]
    pyproject_text = _read_text(root / "pyproject.toml")
    python_version_text = _read_text(root / ".python-version").strip()
    ci_text = _read_text(root / ".github" / "workflows" / "ci.yml")
    dockerfile_text = _read_text(root / "Dockerfile")
    required_specifier = _pyproject_requires_python(pyproject_text)
    minimum_supported = _minimum_python_from_requires(required_specifier)
    current_version = ".".join(str(part) for part in sys.version_info[:3])
    current_major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    current_supported = (
        sys.version_info[:2] >= minimum_supported if minimum_supported is not None else True
    )
    target_version = (
        f"{minimum_supported[0]}.{minimum_supported[1]}" if minimum_supported else ""
    )
    ci_targets_python = bool(target_version and f'python-version: "{target_version}"' in ci_text)
    docker_targets_python = bool(target_version and f"python:{target_version}" in dockerfile_text)
    python_version_file_matches = python_version_text == target_version if target_version else False
    project_targets_aligned = bool(
        target_version and ci_targets_python and docker_targets_python and python_version_file_matches
    )
    return {
        "collector_path": "app/services/status_python_runtime.py",
        "current_version": current_version,
        "current_major_minor": current_major_minor,
        "implementation": sys.implementation.name,
        "executable": sys.executable,
        "required_specifier": required_specifier,
        "minimum_supported": target_version,
        "current_runtime_supported": current_supported,
        "python_version_file": python_version_text,
        "python_version_file_matches": python_version_file_matches,
        "ci_targets_python": ci_targets_python,
        "docker_targets_python": docker_targets_python,
        "project_targets_aligned": project_targets_aligned,
        "bootstrap_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --apply --replace-existing",
        "bootstrap_dry_run_cli": ".venv/bin/python scripts/bootstrap_python_runtime.py --json",
        "bootstrap_backup_policy": "Unsupported existing .venv is moved to .venv.backup-<timestamp> only with --replace-existing.",
        "interpreter_install_hints": _python_interpreter_install_hints(target_version),
        "recommended_action": (
            "Install a supported Python interpreter if needed, then rebuild .venv with "
            f"Python {target_version}+ before production startup."
            if target_version and not current_supported
            else None
        ),
    }


def _python_interpreter_install_hints(target_version: str) -> list[dict[str, str]]:
    version = str(target_version or "").strip()
    if not version:
        return []
    return [
        {
            "tool": "homebrew",
            "command": f"brew install python@{version}",
            "venv_command": f"python{version} -m venv .venv",
        },
        {
            "tool": "pyenv",
            "command": f"pyenv install {version}",
            "venv_command": f"pyenv local {version} && python -m venv .venv",
        },
        {
            "tool": "uv",
            "command": f"uv python install {version}",
            "venv_command": f"uv venv --python {version} .venv",
        },
    ]


def _pyproject_requires_python(pyproject_text: str) -> str:
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("requires-python"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _minimum_python_from_requires(specifier: str) -> tuple[int, int] | None:
    marker = ">="
    if marker not in specifier:
        return None
    version = specifier.split(marker, 1)[1].split(",", 1)[0].strip()
    parts = version.split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
