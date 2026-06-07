from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXTRAS = "dev,pdf,visual,browser,graph"
KNOWN_BOOTSTRAP_PYTHON_VERSIONS = ("3.11", "3.12", "3.13")
INSPECT_CODE = (
    "import json, sys; "
    "print(json.dumps({'executable': sys.executable, "
    "'version': '.'.join(str(part) for part in sys.version_info[:3]), "
    "'major': sys.version_info[0], 'minor': sys.version_info[1]}))"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or rebuild the project .venv with the Python runtime declared by pyproject."
    )
    parser.add_argument(
        "--python",
        dest="requested_python",
        help="Preferred Python interpreter command or absolute path, for example python3.11.",
    )
    parser.add_argument(
        "--install-extras",
        default=DEFAULT_EXTRAS,
        help=(
            "Comma-separated project extras to install after creating .venv. "
            "Use an empty value to install the base project only."
        ),
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Only create the virtualenv; do not run pip install.",
    )
    parser.add_argument(
        "--install-playwright-browser",
        action="store_true",
        help="Also run playwright install chromium after dependency installation.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="If an unsupported .venv exists, move it to a timestamped backup before rebuilding.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the plan. Without this flag the script only prints the plan.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    plan = plan_python_runtime_bootstrap(
        root=ROOT,
        requested_python=args.requested_python,
        install_extras=args.install_extras,
        skip_install=bool(args.skip_install),
        install_playwright_browser=bool(args.install_playwright_browser),
    )
    result = plan
    if args.apply:
        result = apply_python_runtime_bootstrap(
            plan,
            replace_existing=bool(args.replace_existing),
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_bootstrap_result(result))
    return bootstrap_exit_code(result, apply=bool(args.apply))


def plan_python_runtime_bootstrap(
    *,
    root: Path,
    requested_python: str | None = None,
    install_extras: str = DEFAULT_EXTRAS,
    skip_install: bool = False,
    install_playwright_browser: bool = False,
) -> dict:
    root = Path(root)
    required_specifier = pyproject_requires_python(root / "pyproject.toml")
    minimum_supported = minimum_python_from_requires(required_specifier) or (3, 11)
    target_version = python_version_target(root, minimum_supported)
    venv_python = root / ".venv" / "bin" / "python"
    existing = inspect_interpreter(str(venv_python)) if venv_python.exists() else None
    if existing:
        existing["supported"] = interpreter_supported(existing, minimum_supported)

    candidates = []
    for command in candidate_interpreter_commands(
        target_version=target_version,
        requested_python=requested_python,
    ):
        inspected = inspect_interpreter(command)
        if not inspected:
            continue
        inspected["command"] = command
        inspected["supported"] = interpreter_supported(inspected, minimum_supported)
        candidates.append(inspected)
    selected = next((candidate for candidate in candidates if candidate.get("supported")), None)

    status = "planned"
    if existing and existing.get("supported"):
        status = "ready"
    elif not selected:
        status = "missing_supported_interpreter"
    elif existing and not existing.get("supported"):
        status = "replace_required"

    extras = normalize_extras(install_extras)
    commands = planned_commands(
        selected_interpreter=selected,
        install_extras=extras,
        skip_install=skip_install,
        install_playwright_browser=install_playwright_browser,
        create_venv=not bool(existing and existing.get("supported")),
    )
    return {
        "status": status,
        "root": str(root),
        "required_specifier": required_specifier,
        "minimum_supported": f"{minimum_supported[0]}.{minimum_supported[1]}",
        "target_version": target_version,
        "venv_python": ".venv/bin/python",
        "existing_venv": existing,
        "selected_interpreter": selected,
        "candidate_interpreters": candidates,
        "install_extras": extras,
        "skip_install": bool(skip_install),
        "install_playwright_browser": bool(install_playwright_browser),
        "commands": commands,
        "interpreter_install_hints": interpreter_install_hints(target_version),
        "safe_apply": {
            "dry_run_by_default": True,
            "replace_existing_required": bool(existing and not existing.get("supported")),
            "backup_existing_venv": bool(existing and not existing.get("supported")),
        },
        "remediation": remediation_for_status(status, target_version),
    }


def apply_python_runtime_bootstrap(plan: dict, *, replace_existing: bool = False) -> dict:
    result = dict(plan)
    root = Path(str(plan.get("root") or ROOT))
    venv_dir = root / ".venv"
    existing = plan.get("existing_venv") or {}
    selected = plan.get("selected_interpreter") or {}
    if plan.get("status") == "missing_supported_interpreter":
        result.update({"status": "missing_supported_interpreter", "applied": False})
        return result
    if existing and not existing.get("supported") and not replace_existing:
        result.update(
            {
                "status": "blocked",
                "applied": False,
                "error": "unsupported_existing_venv_requires_replace_existing",
            }
        )
        return result
    if not selected and not (existing and existing.get("supported")):
        result.update({"status": "blocked", "applied": False, "error": "no_supported_interpreter"})
        return result

    executed: list[list[str]] = []
    backups: list[str] = []
    if existing and not existing.get("supported"):
        backup_path = unique_backup_path(root)
        shutil.move(str(venv_dir), str(backup_path))
        backups.append(str(backup_path))

    if not (existing and existing.get("supported")):
        command = [str(selected["executable"]), "-m", "venv", str(venv_dir)]
        run_command(command, cwd=root)
        executed.append(command)

    venv_python = venv_dir / "bin" / "python"
    if not plan.get("skip_install"):
        command = [str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools"]
        run_command(command, cwd=root)
        executed.append(command)
        install_target = project_install_target(str(plan.get("install_extras") or ""))
        command = [str(venv_python), "-m", "pip", "install", "-e", install_target]
        run_command(command, cwd=root)
        executed.append(command)
    if plan.get("install_playwright_browser"):
        command = [str(venv_python), "-m", "playwright", "install", "chromium"]
        run_command(command, cwd=root)
        executed.append(command)

    result.update(
        {
            "status": "applied",
            "applied": True,
            "backup_paths": backups,
            "executed_commands": [display_command(command, root=root) for command in executed],
        }
    )
    return result


def format_bootstrap_result(result: dict) -> str:
    lines = [
        f"Python runtime bootstrap: {result.get('status')}",
        f"- target: Python {result.get('minimum_supported')}+ ({result.get('required_specifier')})",
    ]
    existing = result.get("existing_venv")
    if existing:
        lines.append(
            "- existing .venv: "
            f"Python {existing.get('version')} "
            f"({'supported' if existing.get('supported') else 'unsupported'})"
        )
    selected = result.get("selected_interpreter")
    if selected:
        lines.append(
            "- selected interpreter: "
            f"{selected.get('command')} -> Python {selected.get('version')}"
        )
    if result.get("remediation"):
        lines.append(f"- remediation: {result['remediation']}")
    if result.get("backup_paths"):
        lines.append("- backups: " + ", ".join(str(path) for path in result["backup_paths"]))
    install_hints = result.get("interpreter_install_hints") or []
    if result.get("status") == "missing_supported_interpreter" and install_hints:
        lines.append("- install Python first:")
        for hint in install_hints:
            if isinstance(hint, dict) and hint.get("command"):
                lines.append(f"  {hint['command']}")
    commands = result.get("commands") or result.get("executed_commands") or []
    if commands:
        lines.append("- commands:")
        lines.extend(f"  {command}" for command in commands)
    return "\n".join(lines)


def bootstrap_exit_code(result: dict, *, apply: bool) -> int:
    status = str(result.get("status") or "")
    if status in {"planned", "ready", "applied"}:
        return 0
    if status == "replace_required" and not apply:
        return 0
    if status == "missing_supported_interpreter":
        return 2
    if status == "blocked":
        return 3
    return 1


def pyproject_requires_python(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("requires-python"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ">=3.11"


def minimum_python_from_requires(specifier: str) -> tuple[int, int] | None:
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


def python_version_target(root: Path, minimum_supported: tuple[int, int]) -> str:
    version_file = root / ".python-version"
    if version_file.exists():
        value = version_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    return f"{minimum_supported[0]}.{minimum_supported[1]}"


def candidate_interpreter_commands(
    *,
    target_version: str,
    requested_python: str | None = None,
) -> list[str]:
    commands = [
        requested_python,
        os.environ.get("PYTHON_BOOTSTRAP_INTERPRETER"),
        *candidate_versioned_interpreter_commands(target_version),
        "python3",
        "python",
    ]
    deduped: list[str] = []
    for command in commands:
        if not command or command in deduped:
            continue
        deduped.append(command)
    return deduped


def candidate_versioned_interpreter_commands(target_version: str) -> list[str]:
    target = parse_major_minor(target_version)
    versions = [str(target_version).strip()] if str(target_version or "").strip() else []
    known_versions = list(KNOWN_BOOTSTRAP_PYTHON_VERSIONS)
    if target:
        supported_known = [
            version for version in known_versions if parse_major_minor(version) >= target
        ]
        older_known = [version for version in known_versions if parse_major_minor(version) < target]
        versions.extend(sorted(supported_known, key=parse_major_minor))
        versions.extend(sorted(older_known, key=parse_major_minor, reverse=True))
    else:
        versions.extend(known_versions)
    return [f"python{version}" for version in dict.fromkeys(versions)]


def parse_major_minor(value: str) -> tuple[int, int] | None:
    parts = str(value or "").strip().split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def inspect_interpreter(command: str) -> dict | None:
    executable = command if os.path.sep in command else shutil.which(command)
    if not executable:
        return None
    path = Path(executable)
    if os.path.sep in command and not path.exists():
        return None
    try:
        completed = subprocess.run(
            [str(path), "-c", INSPECT_CODE],
            check=False,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return None
    return {
        "command": command,
        "executable": str(payload.get("executable") or path),
        "version": str(payload.get("version") or ""),
        "major": int(payload.get("major") or 0),
        "minor": int(payload.get("minor") or 0),
    }


def interpreter_supported(interpreter: dict, minimum_supported: tuple[int, int]) -> bool:
    return (int(interpreter.get("major") or 0), int(interpreter.get("minor") or 0)) >= minimum_supported


def planned_commands(
    *,
    selected_interpreter: dict | None,
    install_extras: str,
    skip_install: bool,
    install_playwright_browser: bool,
    create_venv: bool,
) -> list[str]:
    commands = []
    if create_venv and selected_interpreter:
        commands.append(f"{selected_interpreter['command']} -m venv .venv")
    if not skip_install:
        commands.append(".venv/bin/python -m pip install --upgrade pip setuptools")
        commands.append(f'.venv/bin/python -m pip install -e "{project_install_target(install_extras)}"')
    if install_playwright_browser:
        commands.append(".venv/bin/python -m playwright install chromium")
    return commands


def interpreter_install_hints(target_version: str) -> list[dict[str, str]]:
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


def normalize_extras(value: str | None) -> str:
    extras = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return ",".join(dict.fromkeys(extras))


def project_install_target(extras: str) -> str:
    return f".[{extras}]" if extras else "."


def remediation_for_status(status: str, target_version: str) -> str | None:
    if status == "missing_supported_interpreter":
        install_commands = ", ".join(
            hint["command"] for hint in interpreter_install_hints(target_version)
        )
        return (
            f"Install Python {target_version}+ first with one of these commands: "
            f"{install_commands}."
        )
    if status == "replace_required":
        return (
            "Existing .venv uses an unsupported runtime. Re-run with --apply --replace-existing "
            "to move it to a timestamped backup and rebuild."
        )
    if status == "ready":
        return "Current .venv already satisfies the runtime target; dependency install can still be rerun."
    return None


def unique_backup_path(root: Path) -> Path:
    stamp = time.strftime("%Y%m%d%H%M%S")
    base = root / f".venv.backup-{stamp}"
    if not base.exists():
        return base
    suffix = 1
    while True:
        candidate = root / f".venv.backup-{stamp}-{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def run_command(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {display_command(command, root=cwd)}")


def display_command(command: list[str], *, root: Path) -> str:
    displayed = []
    for part in command:
        try:
            path = Path(part)
            if path.is_absolute() and path.is_relative_to(root):
                displayed.append(str(path.relative_to(root)))
                continue
        except ValueError:
            pass
        displayed.append(part)
    return " ".join(displayed)


if __name__ == "__main__":
    sys.exit(main())
