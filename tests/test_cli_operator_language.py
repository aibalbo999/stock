from __future__ import annotations

from pathlib import Path


OPERATOR_SCRIPT_SOURCES = [
    Path("scripts/system_backup.py"),
    Path("scripts/external_deployment_env_gaps.py"),
    Path("scripts/structured_company_filing_fixture_smoke.py"),
    Path("scripts/local_structured_company_filing_api.py"),
    Path("scripts/evaluate_visual_rag.py"),
    Path("scripts/frontend_smoke.py"),
    Path("scripts/evaluate_graphrag_reasoning.py"),
    Path("scripts/llm_quota_env_audit.py"),
    Path("scripts/upgrade_audit.py"),
    Path("scripts/external_integrations_smoke.py"),
    Path("scripts/bootstrap_python_runtime.py"),
    Path("app/services/system_backup.py"),
]

FORBIDDEN_OPERATOR_HELP_TEXT = [
    "Print machine-readable JSON",
    "Return non-zero when not ready",
    "Local structured filing fixture was not ready within",
    "Backup command:",
    "Restore SQLite database",
    "Restore {len(artifacts)} report files",
]


def test_operator_cli_help_and_backup_descriptions_use_local_language() -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in OPERATOR_SCRIPT_SOURCES)

    for forbidden in FORBIDDEN_OPERATOR_HELP_TEXT:
        assert forbidden not in sources
