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
    neo4j_ci_smoke_source = Path("scripts/ci_neo4j_graphrag_live_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "python-version" in str(job)
    assert '"3.11"' in workflow_path.read_text(encoding="utf-8")
    assert "redis" in job["services"]
    assert "neo4j" in job["services"]
    assert job["services"]["neo4j"]["image"] == "neo4j:5-community"
    assert "python -m playwright install --with-deps chromium" in step_text
    assert "ruff check ." in step_text
    assert "scripts/security_scan.py --engine detect-secrets" in step_text
    assert "pytest -q" in step_text
    assert "scripts/upgrade_audit.py --json" in step_text
    assert "scripts/external_integrations_smoke.py --json" in step_text
    assert "scripts/company_filing_render_smoke.py" in step_text
    assert "--min-text-chars 20" in step_text
    assert "COMPANY_FILING_PLAYWRIGHT_RENDER_ENABLED" in str(job["steps"])
    assert "scripts/ci_neo4j_graphrag_live_smoke.py --timeout-seconds 90" in step_text
    assert "neo4j_graphrag_smoke.main" in neo4j_ci_smoke_source
    assert "--import-first" in neo4j_ci_smoke_source
    assert "--strict" in neo4j_ci_smoke_source
    assert "NEO4J_URI" in str(job["steps"])
    assert "NEO4J_AUTH" in str(job["steps"])
    assert "NEO4J_PASSWORD: stock_ai_neo4j_password" not in workflow_path.read_text(encoding="utf-8")
    assert "scripts/structured_company_filing_smoke.py" in step_text
    assert "--sample-json examples/structured_company_filing_sample.json" in step_text
    assert "--document-type investor_presentation" in step_text
    assert "scripts/evaluate_graphrag_reasoning.py" in step_text
    assert "data/graphrag_reasoning_golden.jsonl" in step_text
    assert "scripts/evaluate_visual_rag.py" in step_text
    assert "scripts/frontend_smoke.py" in step_text
    assert "--skip-browser" in step_text
    assert "/llm/usage/summary?days=7" in step_text


def test_project_runtime_targets_python311() -> None:
    assert 'requires-python = ">=3.11"' in Path("pyproject.toml").read_text(encoding="utf-8")
    assert Path(".python-version").read_text(encoding="utf-8").strip() == "3.11"
