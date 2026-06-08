from __future__ import annotations

from pathlib import Path

from app.services.runtime_identity import runtime_identity_status


def test_runtime_identity_prefers_build_env_commit() -> None:
    status = runtime_identity_status(
        root=Path("."),
        environ={
            "STOCK_AI_BUILD_COMMIT": "commit-main-test",
            "STOCK_AI_BUILD_BRANCH": "main",
        },
        command_runner=lambda args, _root: "" if args == ["status", "--porcelain"] else None,
    )

    assert status["collector_path"] == "app/services/runtime_identity.py"
    assert status["source"] == "env"
    assert status["git_commit"] == "commit-main-test"
    assert status["git_commit_short"] == "commit-main-"
    assert status["git_branch"] == "main"
    assert status["build_commit_env_configured"] is True


def test_runtime_identity_falls_back_to_git_runner() -> None:
    def fake_git(args, _root):
        if args == ["rev-parse", "HEAD"]:
            return "commit-feature-test"
        if args == ["branch", "--show-current"]:
            return "feature/runtime-identity"
        if args == ["status", "--porcelain"]:
            return " M app.py"
        return None

    status = runtime_identity_status(
        root=Path("."),
        environ={},
        command_runner=fake_git,
    )

    assert status["source"] == "git"
    assert status["git_commit"] == "commit-feature-test"
    assert status["git_commit_short"] == "commit-featu"
    assert status["git_branch"] == "feature/runtime-identity"
    assert status["git_dirty"] is True
    assert status["git_available"] is True
