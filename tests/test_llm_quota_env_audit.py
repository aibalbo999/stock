from __future__ import annotations

import json
from pathlib import Path

from app.services.llm_quota_env_audit import (
    format_llm_quota_env_audit,
    llm_quota_env_audit,
)
from scripts import llm_quota_env_audit as llm_quota_env_audit_cli


def test_llm_quota_env_audit_reports_ready_without_exposing_secrets(tmp_path) -> None:
    audit_source = Path("app/services/llm_quota_env_audit.py").read_text()
    reference_source = Path("app/services/llm_quota_reference.py").read_text()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "UNRELATED_ENV=plain",
                (
                    "LLM_MODEL_DAILY_REQUEST_BUDGETS="
                    "gemini-3.5-flash=250,"
                    "gemini-2.5-flash=250,"
                    "gemini-2.5-flash-lite=1000,"
                    "gemma-4-31b-it=14400"
                ),
            ]
        ),
        encoding="utf-8",
    )

    report = llm_quota_env_audit(env_file=env_file)
    formatted = format_llm_quota_env_audit(report)

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["drift_count"] == 0
    assert report["invalid_count"] == 0
    assert any(
        row["model_key"] == "gemini-3.5-flash"
        and row["status"] == "project_configured_reference"
        for row in report["rows"]
    )
    assert any(
        row["model_key"] == "gemini-2.5-flash-lite"
        and row["official_free_tier_request_budget_reference"] == 1000
        for row in report["rows"]
    )
    assert "plain" not in json.dumps(report, ensure_ascii=False)
    assert "plain" not in formatted
    assert "LLM 額度環境檢查: ready" in formatted
    assert "模型數=4；漂移=0；無效=0" in formatted
    assert "環境檔:" in formatted
    assert "建議下一步:" in formatted
    assert "已設定=250" in formatted
    assert "參考額度=250" in formatted
    assert "LLM quota env audit" not in formatted
    assert "Next action" not in formatted
    assert "def _quota_reference_source(" not in audit_source
    assert "def quota_reference_source(" in reference_source


def test_llm_quota_env_audit_detects_drift_and_strict_cli_exits_nonzero(
    tmp_path,
    capsys,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_MODEL_DAILY_REQUEST_BUDGETS=gemini-2.5-flash-lite=250\n",
        encoding="utf-8",
    )

    report = llm_quota_env_audit(env_file=env_file)

    assert report["status"] == "drift_detected"
    assert report["ready"] is False
    assert report["drift_count"] == 1
    assert report["rows"][0]["model_key"] == "gemini-2.5-flash-lite"
    assert report["rows"][0]["configured_request_budget"] == 250
    assert report["rows"][0]["official_free_tier_request_budget_reference"] == 1000

    exit_code = llm_quota_env_audit_cli.main(
        ["--env-file", str(env_file), "--json", "--strict"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["status"] == "drift_detected"
    assert payload["drift_count"] == 1


def test_llm_quota_env_audit_apply_updates_only_reference_budget_line(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "UNRELATED_ENV=plain",
                (
                    "LLM_MODEL_DAILY_REQUEST_BUDGETS="
                    "gemini-3.5-flash=250,"
                    "gemini-2.5-flash-lite=250,"
                    "gemma-4-31b-it=14400"
                ),
                "OTHER_VALUE=kept",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = llm_quota_env_audit(env_file=env_file, apply_reference_budgets=True)
    contents = env_file.read_text(encoding="utf-8")

    assert report["status"] == "ready"
    assert report["apply"] == {
        "applied": True,
        "updated_models": ["gemini-2.5-flash-lite"],
        "reason": "reference_budgets_applied",
    }
    assert "gemini-2.5-flash-lite=1000" in contents
    assert "gemini-3.5-flash=250" in contents
    assert "gemma-4-31b-it=14400" in contents
    assert "UNRELATED_ENV=plain" in contents
    assert "OTHER_VALUE=kept" in contents
    assert "已套用: gemini-2.5-flash-lite" in format_llm_quota_env_audit(report)


def test_llm_quota_env_audit_missing_env_key_is_action_required(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("UNRELATED_ENV=plain\n", encoding="utf-8")

    report = llm_quota_env_audit(env_file=env_file)

    assert report["status"] == "missing_budget_env_key"
    assert report["ready"] is False
    assert report["rows"] == []
    assert "plain" not in json.dumps(report, ensure_ascii=False)
