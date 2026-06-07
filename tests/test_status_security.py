from __future__ import annotations

from app.services import status_security
from app.services.status_security import security_scan_status


def test_security_status_finds_detect_secrets_in_current_python_bin(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(status_security.shutil, "which", lambda _engine: None)
    monkeypatch.setattr(status_security.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(
        status_security.sys,
        "executable",
        str(tmp_path / "bin" / "python"),
    )
    tool = tmp_path / "bin" / "detect-secrets"
    hook = tmp_path / "bin" / "detect-secrets-hook"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    hook.write_text("#!/bin/sh\n", encoding="utf-8")

    status = security_scan_status(module_available=lambda name: name == "detect_secrets")

    assert status["detect_secrets_cli_available"] is True
    assert status["detect_secrets_hook_available"] is True
    assert status["external_engine_available"] is True
    assert status["default_engine"] == "detect-secrets"
    assert status["default_engine_external"] is True
    assert status["local_regex_active"] is False
    assert status["baseline_read_only_default"] is True
    assert status["baseline_update_flag"] == "--update-baseline"


def test_security_status_marks_regex_as_active_only_when_external_engines_missing(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(status_security.shutil, "which", lambda _engine: None)
    monkeypatch.setattr(status_security.sys, "prefix", str(tmp_path / "empty-prefix"))
    monkeypatch.setattr(
        status_security.sys,
        "executable",
        str(tmp_path / "empty-bin" / "python"),
    )

    status = security_scan_status(module_available=lambda _name: False)

    assert status["detect_secrets_cli_available"] is False
    assert status["gitleaks_cli_available"] is False
    assert status["external_engine_available"] is False
    assert status["default_engine"] == "local_regex"
    assert status["default_engine_external"] is False
    assert status["local_regex_active"] is True
    assert status["local_regex_fallback_role"] == "fallback_only"
