from pathlib import Path

from app.services import persistence
from app.services.llm_usage_repository import LLMUsageRepository


def test_llm_usage_repository_lives_outside_persistence_module() -> None:
    persistence_source = Path("app/services/persistence.py").read_text()
    repository_source = Path("app/services/llm_usage_repository.py").read_text()

    assert persistence.LLMUsageRepository is LLMUsageRepository
    assert "class LLMUsageRepository:" not in persistence_source
    assert "class LLMUsageRepository:" in repository_source
    assert "def create_from_report_execution(" in repository_source
    assert "def to_dict(" in repository_source
