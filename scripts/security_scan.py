from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable


SECRET_PATTERNS = {
    "google_api_key": re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
    "openai_api_key": re.compile(
        r"(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
    ),
    "anthropic_api_key": re.compile(
        r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
    ),
    "private_key": re.compile(r"BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY"),
}

DEFAULT_EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "logs",
    "reports",
}
DEFAULT_EXCLUDED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".png", ".jpg", ".jpeg", ".pdf"}
EXTERNAL_ENGINES = ("detect-secrets", "gitleaks")
LOCAL_ENGINE = "local_regex"
DEFAULT_DETECT_SECRETS_BASELINE = ".secrets.baseline"


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / line for line in result.stdout.splitlines() if line.strip()]


def all_project_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in DEFAULT_EXCLUDED_PARTS for part in path.relative_to(root).parts)
        and path.suffix.lower() not in DEFAULT_EXCLUDED_SUFFIXES
    ]


def scan_paths(paths: list[Path], root: Path) -> list[dict]:
    findings = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS.items():
                for match in pattern.finditer(line):
                    findings.append(
                        {
                            "type": label,
                            "path": str(path.relative_to(root)),
                            "line": line_number,
                            "match": redact(match.group(0)),
                        }
                    )
    return findings


def scan_with_engine(
    paths: list[Path],
    root: Path,
    *,
    engine: str = "auto",
    baseline: Path | None = None,
    update_baseline: bool = False,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[str, list[dict]]:
    resolved = resolve_engine(engine)
    if resolved == "detect-secrets":
        return resolved, run_detect_secrets(
            paths,
            root,
            runner=runner,
            baseline=baseline,
            update_baseline=update_baseline,
        )
    if resolved == "gitleaks":
        return resolved, run_gitleaks(root, runner=runner)
    return LOCAL_ENGINE, scan_paths(paths, root)


def resolve_engine(engine: str) -> str:
    requested = str(engine or "auto").strip().lower()
    if requested in {"local", LOCAL_ENGINE, "regex"}:
        return LOCAL_ENGINE
    if requested == "detect_secrets":
        requested = "detect-secrets"
    if requested in EXTERNAL_ENGINES:
        if not external_engine_available(requested):
            raise RuntimeError(f"security scan engine is not available: {requested}")
        return requested
    if requested != "auto":
        raise RuntimeError(f"unsupported security scan engine: {engine}")
    for candidate in EXTERNAL_ENGINES:
        if external_engine_available(candidate):
            return candidate
    return LOCAL_ENGINE


def external_engine_available(engine: str) -> bool:
    return external_engine_command(engine) is not None


def external_engine_command(engine: str) -> str | None:
    if shutil.which(engine) is not None:
        return engine
    for base in (Path(sys.prefix), Path(sys.executable).parent):
        local_command = base / "bin" / engine if base.name != "bin" else base / engine
        if local_command.exists():
            return str(local_command)
    return None


def run_detect_secrets(
    paths: list[Path],
    root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    baseline: Path | None = None,
    update_baseline: bool = False,
) -> list[dict]:
    baseline_path = baseline or (root / DEFAULT_DETECT_SECRETS_BASELINE)
    relative_paths = [
        str(path.relative_to(root))
        for path in paths
        if path.exists() and path.is_file() and path.resolve() != baseline_path.resolve()
    ]
    if not relative_paths:
        return []
    hook_command = external_engine_command("detect-secrets-hook")
    if baseline_path.exists() and hook_command is not None:
        if update_baseline:
            return _run_detect_secrets_hook(
                hook_command,
                baseline_path,
                relative_paths,
                root,
                runner=runner,
            )
        with tempfile.TemporaryDirectory(prefix="detect-secrets-baseline-") as temp_dir:
            hook_baseline_path = Path(temp_dir) / baseline_path.name
            shutil.copy2(baseline_path, hook_baseline_path)
            return _run_detect_secrets_hook(
                hook_command,
                hook_baseline_path,
                relative_paths,
                root,
                runner=runner,
            )
    command = external_engine_command("detect-secrets")
    if command is None:
        raise RuntimeError("security scan engine is not available: detect-secrets")
    completed = runner(
        [command, "scan", *relative_paths],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError((completed.stderr or completed.stdout or "detect-secrets failed").strip())
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("detect-secrets returned invalid JSON") from exc
    return detect_secrets_findings(payload)


def _run_detect_secrets_hook(
    hook_command: str,
    baseline_path: Path,
    relative_paths: list[str],
    root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict]:
    completed = runner(
        [
            hook_command,
            "--json",
            "--baseline",
            _hook_baseline_arg(baseline_path, root),
            *relative_paths,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return []
    if completed.returncode != 1:
        raise RuntimeError((completed.stderr or completed.stdout or "detect-secrets-hook failed").strip())
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        detail = (completed.stdout or completed.stderr or "").strip()
        if detail:
            raise RuntimeError(detail) from exc
        raise RuntimeError("detect-secrets-hook returned invalid JSON") from exc
    return detect_secrets_hook_findings(payload)


def _hook_baseline_arg(baseline_path: Path, root: Path) -> str:
    try:
        return str(baseline_path.relative_to(root))
    except ValueError:
        return str(baseline_path)


def detect_secrets_findings(payload: dict) -> list[dict]:
    findings = []
    for path, rows in sorted((payload.get("results") or {}).items()):
        for row in rows or []:
            findings.append(
                {
                    "type": f"detect-secrets:{row.get('type') or 'secret'}",
                    "path": str(path),
                    "line": int(row.get("line_number") or 0),
                    "match": "***",
                }
            )
    return findings


def detect_secrets_hook_findings(payload: dict) -> list[dict]:
    findings = []
    for path, rows in sorted((payload.get("results") or {}).items()):
        for row in rows or []:
            findings.append(
                {
                    "type": f"detect-secrets:{row.get('type') or 'secret'}",
                    "path": str(path),
                    "line": int(row.get("line_number") or row.get("line") or 0),
                    "match": "***",
                }
            )
    return findings


def run_gitleaks(
    root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict]:
    command = external_engine_command("gitleaks")
    if command is None:
        raise RuntimeError("security scan engine is not available: gitleaks")
    with tempfile.NamedTemporaryFile(prefix="gitleaks-", suffix=".json") as report_file:
        completed = runner(
            [
                command,
                "detect",
                "--source",
                str(root),
                "--redact",
                "--exit-code",
                "1",
                "--no-banner",
                "--report-format",
                "json",
                "--report-path",
                report_file.name,
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        try:
            report_text = Path(report_file.name).read_text(encoding="utf-8")
        except OSError:
            report_text = ""
    if completed.returncode == 0:
        return []
    if completed.returncode == 1:
        try:
            payload = json.loads(report_text or "[]")
        except json.JSONDecodeError as exc:
            detail = (completed.stderr or completed.stdout or report_text or "").strip()
            if detail:
                raise RuntimeError(detail[:4000]) from exc
            raise RuntimeError("gitleaks returned invalid JSON report") from exc
        findings = gitleaks_findings(payload)
        if findings:
            return findings
        return [_gitleaks_fallback_finding(completed.stderr or completed.stdout)]
    raise RuntimeError((completed.stderr or completed.stdout or "gitleaks failed").strip())


def gitleaks_findings(payload: object) -> list[dict]:
    rows = payload.get("findings") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    findings = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rule = row.get("RuleID") or row.get("rule_id") or row.get("rule") or row.get("Description")
        path = row.get("File") or row.get("file") or row.get("path") or "<gitleaks>"
        line = row.get("StartLine") or row.get("start_line") or row.get("line") or 0
        detail = row.get("Description") or row.get("description") or row.get("Fingerprint")
        findings.append(
            {
                "type": f"gitleaks:{rule or 'finding'}",
                "path": str(path),
                "line": int(line or 0),
                "match": "***",
                **({"detail": str(detail)[:4000]} if detail else {}),
            }
        )
    return findings


def _gitleaks_fallback_finding(detail: str | None = None) -> dict:
    return {
        "type": "gitleaks:finding",
        "path": "<gitleaks>",
        "line": 0,
        "match": "***",
        "detail": str(detail or "gitleaks detected a secret").strip()[:4000],
    }


def redact(value: str) -> str:
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan tracked project files for committed secrets.")
    parser.add_argument("--all", action="store_true", help="Scan all non-cache project files instead of git tracked files.")
    parser.add_argument(
        "--engine",
        default="auto",
        choices=("auto", "detect-secrets", "gitleaks", "local", LOCAL_ENGINE),
        help="Secret scanning engine. auto prefers detect-secrets/gitleaks, then local regex fallback.",
    )
    parser.add_argument(
        "--baseline",
        default=DEFAULT_DETECT_SECRETS_BASELINE,
        help="detect-secrets baseline used to ignore audited placeholders and test fixtures.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Allow detect-secrets-hook to update the real baseline. Default scans use a temporary copy.",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    paths = all_project_files(root) if args.all else tracked_files(root)
    try:
        engine, findings = scan_with_engine(
            paths,
            root,
            engine=args.engine,
            baseline=root / args.baseline,
            update_baseline=args.update_baseline,
        )
    except RuntimeError as exc:
        print(f"Security scan failed: {exc}", file=sys.stderr)
        return 2
    if findings:
        for finding in findings:
            print(
                f"{finding['path']}:{finding['line']}: "
                f"{finding['type']} {finding['match']}",
                file=sys.stderr,
            )
            if finding.get("detail"):
                print(str(finding["detail"]), file=sys.stderr)
        return 1
    print(f"No committed secrets found. engine={engine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
