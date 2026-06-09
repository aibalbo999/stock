from pathlib import Path

from app.services import persistence
from app.services.risk_classification_repository import RiskClassificationRepository


def test_risk_classification_repository_lives_outside_persistence_module() -> None:
    persistence_source = Path("app/services/persistence.py").read_text()
    repository_source = Path("app/services/risk_classification_repository.py").read_text()

    assert persistence.RiskClassificationRepository is RiskClassificationRepository
    assert "class RiskClassificationRepository:" not in persistence_source
    assert "class RiskClassificationRepository:" in repository_source
    assert "def get(" in repository_source
    assert "def upsert(" in repository_source
