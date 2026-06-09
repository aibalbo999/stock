from pathlib import Path

from app.services import persistence
from app.services.news_repository import NewsRepository


def test_news_repository_lives_outside_persistence_module() -> None:
    persistence_source = Path("app/services/persistence.py").read_text()
    news_repository_source = Path("app/services/news_repository.py").read_text()

    assert persistence.NewsRepository is NewsRepository
    assert "class NewsRepository:" not in persistence_source
    assert "class NewsRepository:" in news_repository_source
    assert "def _parse_entity_matches(" in news_repository_source
    assert "def _entity_match_values(" in news_repository_source
