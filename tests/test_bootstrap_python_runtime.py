from __future__ import annotations

from pathlib import Path

from scripts import bootstrap_python_runtime as bootstrap


def _write_project_files(root: Path) -> None:
    root.joinpath("pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    root.joinpath(".python-version").write_text("3.11\n", encoding="utf-8")


def _interpreter(command: str, version: str, major: int, minor: int) -> dict:
    return {
        "command": command,
        "executable": f"/fake/{command}",
        "version": version,
        "major": major,
        "minor": minor,
    }


def test_candidate_interpreters_prefer_target_then_closest_newer(monkeypatch) -> None:
    monkeypatch.delenv("PYTHON_BOOTSTRAP_INTERPRETER", raising=False)

    commands = bootstrap.candidate_interpreter_commands(target_version="3.11")

    assert commands[:5] == ["python3.11", "python3.12", "python3.13", "python3", "python"]


def test_plan_selects_supported_python_and_builds_install_commands(tmp_path, monkeypatch) -> None:
    _write_project_files(tmp_path)

    def fake_inspect(command: str) -> dict | None:
        if command == "python3.11":
            return _interpreter(command, "3.11.9", 3, 11)
        if command.endswith(".venv/bin/python"):
            return None
        return None

    monkeypatch.setattr(bootstrap, "inspect_interpreter", fake_inspect)

    plan = bootstrap.plan_python_runtime_bootstrap(root=tmp_path)

    assert plan["status"] == "planned"
    assert plan["minimum_supported"] == "3.11"
    assert plan["selected_interpreter"]["command"] == "python3.11"
    assert "python3.11 -m venv .venv" in plan["commands"]
    assert '.venv/bin/python -m pip install -e ".[dev,pdf,visual,browser,graph]"' in plan[
        "commands"
    ]
    assert plan["interpreter_install_hints"][0] == {
        "tool": "homebrew",
        "command": "brew install python@3.11",
        "venv_command": "python3.11 -m venv .venv",
    }
    assert plan["safe_apply"]["dry_run_by_default"] is True


def test_plan_marks_supported_existing_venv_ready(tmp_path, monkeypatch) -> None:
    _write_project_files(tmp_path)
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    def fake_inspect(command: str) -> dict | None:
        if command.endswith(".venv/bin/python"):
            return {
                **_interpreter(command, "3.11.7", 3, 11),
                "executable": str(venv_python),
            }
        return None

    monkeypatch.setattr(bootstrap, "inspect_interpreter", fake_inspect)

    plan = bootstrap.plan_python_runtime_bootstrap(root=tmp_path)

    assert plan["status"] == "ready"
    assert plan["existing_venv"]["supported"] is True
    assert all("-m venv" not in command for command in plan["commands"])
    assert ".venv/bin/python -m pip install --upgrade pip setuptools" in plan["commands"]


def test_plan_reports_missing_supported_interpreter(tmp_path, monkeypatch) -> None:
    _write_project_files(tmp_path)
    monkeypatch.setattr(bootstrap, "inspect_interpreter", lambda _command: None)

    plan = bootstrap.plan_python_runtime_bootstrap(root=tmp_path)

    assert plan["status"] == "missing_supported_interpreter"
    assert plan["selected_interpreter"] is None
    assert "Install Python 3.11+" in plan["remediation"]
    assert "brew install python@3.11" in plan["remediation"]
    assert plan["interpreter_install_hints"][1]["command"] == "pyenv install 3.11"

    formatted = bootstrap.format_bootstrap_result(plan)
    assert "install Python first" in formatted
    assert "uv python install 3.11" in formatted


def test_apply_refuses_to_replace_unsupported_venv_without_flag(tmp_path, monkeypatch) -> None:
    _write_project_files(tmp_path)
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    def fake_inspect(command: str) -> dict | None:
        if command.endswith(".venv/bin/python"):
            return {
                **_interpreter(command, "3.9.6", 3, 9),
                "executable": str(venv_python),
            }
        if command == "python3.11":
            return _interpreter(command, "3.11.9", 3, 11)
        return None

    monkeypatch.setattr(bootstrap, "inspect_interpreter", fake_inspect)
    monkeypatch.setattr(
        bootstrap,
        "run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    plan = bootstrap.plan_python_runtime_bootstrap(root=tmp_path)
    result = bootstrap.apply_python_runtime_bootstrap(plan, replace_existing=False)

    assert plan["status"] == "replace_required"
    assert result["status"] == "blocked"
    assert result["error"] == "unsupported_existing_venv_requires_replace_existing"
    assert venv_python.exists()


def test_apply_backs_up_and_rebuilds_unsupported_venv(tmp_path, monkeypatch) -> None:
    _write_project_files(tmp_path)
    old_marker = tmp_path / ".venv" / "old.txt"
    old_marker.parent.mkdir(parents=True)
    old_marker.write_text("old", encoding="utf-8")
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    def fake_inspect(command: str) -> dict | None:
        if command.endswith(".venv/bin/python"):
            return {
                **_interpreter(command, "3.9.6", 3, 9),
                "executable": str(venv_python),
            }
        if command == "python3.11":
            return _interpreter(command, "3.11.9", 3, 11)
        return None

    executed: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        executed.append(command)
        if command[1:3] == ["-m", "venv"]:
            rebuilt_python = cwd / ".venv" / "bin" / "python"
            rebuilt_python.parent.mkdir(parents=True)
            rebuilt_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "inspect_interpreter", fake_inspect)
    monkeypatch.setattr(bootstrap, "run_command", fake_run)
    monkeypatch.setattr(bootstrap.time, "strftime", lambda _fmt: "20260102030405")

    plan = bootstrap.plan_python_runtime_bootstrap(root=tmp_path, skip_install=False)
    result = bootstrap.apply_python_runtime_bootstrap(plan, replace_existing=True)

    assert result["status"] == "applied"
    assert result["backup_paths"] == [str(tmp_path / ".venv.backup-20260102030405")]
    assert (tmp_path / ".venv.backup-20260102030405" / "old.txt").read_text(
        encoding="utf-8"
    ) == "old"
    assert (tmp_path / ".venv" / "bin" / "python").exists()
    assert executed[0] == ["/fake/python3.11", "-m", "venv", str(tmp_path / ".venv")]
    assert executed[1][:5] == [
        str(tmp_path / ".venv" / "bin" / "python"),
        "-m",
        "pip",
        "install",
        "--upgrade",
    ]
