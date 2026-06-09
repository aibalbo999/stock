from pathlib import Path

from app.services import persistence
from app.services.analysis_run_repository import AnalysisRunRepository


def test_analysis_run_repository_lives_outside_persistence_module() -> None:
    persistence_source = Path("app/services/persistence.py").read_text()
    repository_source = Path("app/services/analysis_run_repository.py").read_text()

    assert persistence.AnalysisRunRepository is AnalysisRunRepository
    assert "class AnalysisRunRepository:" not in persistence_source
    assert "class AnalysisRunRepository:" in repository_source
    assert "def mark_failed(" in repository_source
    assert "def get_by_celery_task_id(" in repository_source
    assert "def clear_orphan_report_refs(" in repository_source
