from pathlib import Path

from app.services import persistence
from app.services.report_repository import ReportRepository


def test_report_repository_lives_outside_persistence_module() -> None:
    persistence_source = Path("app/services/persistence.py").read_text()
    report_repository_source = Path("app/services/report_repository.py").read_text()

    assert persistence.ReportRepository is ReportRepository
    assert "class ReportRepository:" not in persistence_source
    assert "class ReportRepository:" in report_repository_source
    assert "def prune_older_for_topic(" in report_repository_source
    assert "def latest_by_topic(" in report_repository_source
