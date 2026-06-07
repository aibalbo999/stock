from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_runs_quality_gates_and_smoke_checks() -> None:
    workflow_path = Path(".github/workflows/ci.yml")
    assert workflow_path.exists()
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["test"]
    step_text = "\n".join(
        str(step.get("run") or step.get("uses") or "")
        for step in job["steps"]
    )

    assert "python-version" in str(job)
    assert "redis" in job["services"]
    assert "ruff check ." in step_text
    assert "pytest -q" in step_text
    assert "scripts/upgrade_audit.py --json" in step_text
    assert "scripts/external_integrations_smoke.py --json" in step_text
    assert "scripts/evaluate_visual_rag.py" in step_text
    assert "scripts/frontend_smoke.py" in step_text
    assert "--skip-browser" in step_text
    assert "/llm/usage/summary?days=7" in step_text
