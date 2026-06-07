from pathlib import Path
import subprocess

import pytest

from scripts.security_scan import (
    detect_secrets_findings,
    detect_secrets_hook_findings,
    external_engine_command,
    gitleaks_findings,
    resolve_engine,
    run_detect_secrets,
    run_gitleaks,
    scan_paths,
    scan_with_engine,
)


def test_security_scan_ignores_css_classes_and_task_ids(tmp_path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        """
css = "risk-high task-card task-meta"
task_id = "task-abc"
        """,
        encoding="utf-8",
    )

    assert scan_paths([path], tmp_path) == []


def test_security_scan_detects_realistic_api_keys(tmp_path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        'key = "AIza'
        + "A" * 35
        + '"\nopenai = "sk-'
        + "b" * 40
        + '"\nanthropic = "sk-ant-'
        + "c" * 40
        + '"\n',
        encoding="utf-8",
    )

    findings = scan_paths([path], tmp_path)

    assert {finding["type"] for finding in findings} == {
        "anthropic_api_key",
        "google_api_key",
        "openai_api_key",
    }
    assert all(finding["path"] == Path("sample.py").as_posix() for finding in findings)


def test_detect_secrets_findings_parse_baseline_json() -> None:
    findings = detect_secrets_findings(
        {
            "results": {
                "app.py": [
                    {
                        "type": "Secret Keyword",
                        "line_number": 12,
                        "hashed_secret": "abc",
                    }
                ]
            }
        }
    )

    assert findings == [
        {
            "type": "detect-secrets:Secret Keyword",
            "path": "app.py",
            "line": 12,
            "match": "***",
        }
    ]


def test_detect_secrets_hook_findings_parse_json_output() -> None:
    findings = detect_secrets_hook_findings(
        {
            "results": {
                "app.py": [
                    {
                        "type": "Basic Auth Credentials",
                        "line": 3,
                    }
                ]
            }
        }
    )

    assert findings == [
        {
            "type": "detect-secrets:Basic Auth Credentials",
            "path": "app.py",
            "line": 3,
            "match": "***",
        }
    ]


def test_security_scan_auto_uses_local_regex_when_external_engines_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("scripts.security_scan.shutil.which", lambda _engine: None)
    monkeypatch.setattr("scripts.security_scan.sys.prefix", str(tmp_path / "empty-venv"))
    monkeypatch.setattr("scripts.security_scan.sys.executable", str(tmp_path / "empty-bin" / "python"))
    path = tmp_path / "sample.py"
    path.write_text('"sk-' + "b" * 40 + '"', encoding="utf-8")

    engine, findings = scan_with_engine([path], tmp_path, engine="auto")

    assert engine == "local_regex"
    assert findings[0]["type"] == "openai_api_key"


def test_security_scan_can_run_detect_secrets_engine(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("scripts.security_scan.shutil.which", lambda engine: "/bin/detect-secrets" if engine == "detect-secrets" else None)
    path = tmp_path / "sample.py"
    path.write_text("token = 'secret'", encoding="utf-8")
    captured = {}

    def fake_runner(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"results":{"sample.py":[{"type":"Secret Keyword","line_number":1}]}}',
            stderr="",
        )

    engine, findings = scan_with_engine([path], tmp_path, engine="detect-secrets", runner=fake_runner)

    assert engine == "detect-secrets"
    assert captured["command"] == ["detect-secrets", "scan", "sample.py"]
    assert captured["cwd"] == tmp_path
    assert findings[0]["type"] == "detect-secrets:Secret Keyword"


def test_detect_secrets_hook_excludes_baseline_from_scanned_paths(monkeypatch, tmp_path) -> None:
    baseline = tmp_path / ".secrets.baseline"
    baseline.write_text('{"results":{}}', encoding="utf-8")
    path = tmp_path / "sample.py"
    path.write_text("token = 'example'", encoding="utf-8")
    captured = {}

    def fake_engine_command(engine: str):
        return "/bin/detect-secrets-hook" if engine == "detect-secrets-hook" else None

    def fake_runner(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("scripts.security_scan.external_engine_command", fake_engine_command)

    assert run_detect_secrets([baseline, path], tmp_path, runner=fake_runner, baseline=baseline) == []
    assert captured["command"] == [
        "/bin/detect-secrets-hook",
        "--json",
        "--baseline",
        ".secrets.baseline",
        "sample.py",
    ]


def test_detect_secrets_hook_preserves_actionable_non_json_errors(monkeypatch, tmp_path) -> None:
    baseline = tmp_path / ".secrets.baseline"
    baseline.write_text('{"results":{}}', encoding="utf-8")
    path = tmp_path / "sample.py"
    path.write_text("token = 'example'", encoding="utf-8")

    def fake_engine_command(engine: str):
        return "/bin/detect-secrets-hook" if engine == "detect-secrets-hook" else None

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="Your baseline file (.secrets.baseline) is unstaged.\n"
            "`git add .secrets.baseline` to fix this.\n",
            stderr="",
        )

    monkeypatch.setattr("scripts.security_scan.external_engine_command", fake_engine_command)

    with pytest.raises(RuntimeError, match="baseline file"):
        run_detect_secrets([path], tmp_path, runner=fake_runner, baseline=baseline)


def test_gitleaks_findings_parse_json_report() -> None:
    findings = gitleaks_findings(
        [
            {
                "RuleID": "generic-api-key",
                "Description": "Generic API credential",
                "File": "app.py",
                "StartLine": 4,
                "Secret": "***",
            }
        ]
    )

    assert findings == [
        {
            "type": "gitleaks:generic-api-key",
            "path": "app.py",
            "line": 4,
            "match": "***",
            "detail": "Generic API credential",
        }
    ]


def test_security_scan_can_run_gitleaks_engine_with_structured_report(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("scripts.security_scan.shutil.which", lambda engine: "/bin/gitleaks" if engine == "gitleaks" else None)
    captured = {}

    def fake_runner(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        report_path = command[command.index("--report-path") + 1]
        Path(report_path).write_text(
            '[{"RuleID":"generic-api-key","Description":"Generic API credential","File":"app.py","StartLine":9}]',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    findings = run_gitleaks(tmp_path, runner=fake_runner)

    assert captured["command"][:5] == [
        "gitleaks",
        "detect",
        "--source",
        str(tmp_path),
        "--redact",
    ]
    assert "--report-format" in captured["command"]
    assert "json" in captured["command"]
    assert captured["cwd"] == tmp_path
    assert findings == [
        {
            "type": "gitleaks:generic-api-key",
            "path": "app.py",
            "line": 9,
            "match": "***",
            "detail": "Generic API credential",
        }
    ]


def test_security_scan_finds_engine_in_current_python_bin(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("scripts.security_scan.shutil.which", lambda _engine: None)
    monkeypatch.setattr("scripts.security_scan.sys.prefix", str(tmp_path))
    tool = tmp_path / "bin" / "detect-secrets"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n", encoding="utf-8")

    assert external_engine_command("detect-secrets") == str(tool)


def test_security_scan_rejects_unavailable_requested_engine(monkeypatch) -> None:
    monkeypatch.setattr("scripts.security_scan.shutil.which", lambda _engine: None)
    monkeypatch.setattr("scripts.security_scan.sys.prefix", "/tmp/empty-venv-for-security-scan-test")
    monkeypatch.setattr(
        "scripts.security_scan.sys.executable",
        "/tmp/empty-bin-for-security-scan-test/python",
    )

    try:
        resolve_engine("detect-secrets")
    except RuntimeError as exc:
        assert "detect-secrets" in str(exc)
    else:
        raise AssertionError("expected unavailable engine to fail")
