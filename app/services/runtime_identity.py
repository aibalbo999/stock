from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMIT_ENV_KEYS = (
    "STOCK_AI_BUILD_COMMIT",
    "GIT_COMMIT",
    "SOURCE_VERSION",
    "VERCEL_GIT_COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "HEROKU_SLUG_COMMIT",
)
BRANCH_ENV_KEYS = (
    "STOCK_AI_BUILD_BRANCH",
    "GIT_BRANCH",
    "VERCEL_GIT_COMMIT_REF",
    "RENDER_GIT_BRANCH",
)
GitCommandRunner = Callable[[list[str], Path], str | None]


def runtime_identity_status(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    command_runner: GitCommandRunner | None = None,
) -> dict:
    env = os.environ if environ is None else environ
    project_root = Path(root).resolve() if root is not None else PROJECT_ROOT
    run_git = command_runner or _git_output

    env_commit = _first_env_value(env, COMMIT_ENV_KEYS)
    env_branch = _first_env_value(env, BRANCH_ENV_KEYS)
    git_commit = "" if env_commit else (run_git(["rev-parse", "HEAD"], project_root) or "")
    git_branch = "" if env_branch else (run_git(["branch", "--show-current"], project_root) or "")
    git_status = run_git(["status", "--porcelain"], project_root)

    commit = env_commit or git_commit
    branch = env_branch or git_branch
    git_available = bool(git_commit or git_branch or git_status is not None)
    source = "env" if env_commit else "git" if git_commit else "unknown"

    return {
        "collector_path": "app/services/runtime_identity.py",
        "source": source,
        "git_available": git_available,
        "git_commit": commit,
        "git_commit_short": commit[:12] if commit else "",
        "git_branch": branch,
        "git_dirty": bool((git_status or "").strip()) if git_status is not None else None,
        "project_root": str(project_root),
        "build_commit_env_configured": bool(env_commit),
        "build_branch_env_configured": bool(env_branch),
    }


def _first_env_value(env: Mapping[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(env.get(key) or "").strip()
        if value:
            return value
    return ""


def _git_output(args: list[str], root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()
