from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


SECRET_PATTERNS = {
    "google_api_key": re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
    "openai_api_key": re.compile(
        r"(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"
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


def redact(value: str) -> str:
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan tracked project files for committed secrets.")
    parser.add_argument("--all", action="store_true", help="Scan all non-cache project files instead of git tracked files.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    paths = all_project_files(root) if args.all else tracked_files(root)
    findings = scan_paths(paths, root)
    if findings:
        for finding in findings:
            print(
                f"{finding['path']}:{finding['line']}: "
                f"{finding['type']} {finding['match']}",
                file=sys.stderr,
            )
        return 1
    print("No committed secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
