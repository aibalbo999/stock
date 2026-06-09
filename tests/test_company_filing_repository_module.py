from pathlib import Path

from app.services import persistence
from app.services.company_filing_repository import CompanyFilingRepository


def test_company_filing_repository_lives_outside_persistence_module() -> None:
    persistence_source = Path("app/services/persistence.py").read_text()
    repository_source = Path("app/services/company_filing_repository.py").read_text()

    assert persistence.CompanyFilingRepository is CompanyFilingRepository
    assert "class CompanyFilingRepository:" not in persistence_source
    assert "class CompanyFilingRepository:" in repository_source
    assert "def to_news_document(" in repository_source
    assert "def latest_by_tickers(" in repository_source
