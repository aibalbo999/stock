import ast
from pathlib import Path


NEWS_REPOSITORY_CALLER_PATHS = (
    Path("app/services/discovery_workflow.py"),
    Path("app/services/discovery_api.py"),
    Path("app/services/ingestion.py"),
    Path("app/services/followup_evidence_cache.py"),
    Path("app/services/data_operations_api.py"),
    Path("app/services/report_evidence_retrieval.py"),
    Path("app/services/candidate_revalidation.py"),
)

COMPANY_FILING_REPOSITORY_CALLER_PATHS = (
    Path("app/services/company_filing_api.py"),
    Path("app/services/ingestion.py"),
    Path("app/services/followup_evidence_cache.py"),
    Path("app/services/data_operations_api.py"),
    Path("app/services/followup_freshness.py"),
    Path("app/services/report_company_filing_checks.py"),
    Path("app/services/candidate_revalidation.py"),
    Path("app/services/report_evidence_retrieval.py"),
)

RISK_CLASSIFICATION_REPOSITORY_CALLER_PATHS = (Path("app/services/risk_analyzer.py"),)


def test_news_callers_import_repository_directly() -> None:
    _assert_direct_import(
        NEWS_REPOSITORY_CALLER_PATHS,
        direct_module="app.services.news_repository",
        repository_name="NewsRepository",
    )


def test_company_filing_callers_import_repository_directly() -> None:
    _assert_direct_import(
        COMPANY_FILING_REPOSITORY_CALLER_PATHS,
        direct_module="app.services.company_filing_repository",
        repository_name="CompanyFilingRepository",
    )


def test_risk_classification_callers_import_repository_directly() -> None:
    _assert_direct_import(
        RISK_CLASSIFICATION_REPOSITORY_CALLER_PATHS,
        direct_module="app.services.risk_classification_repository",
        repository_name="RiskClassificationRepository",
    )


def _assert_direct_import(
    paths: tuple[Path, ...], *, direct_module: str, repository_name: str
) -> None:
    for path in paths:
        tree = ast.parse(path.read_text())

        assert _imports_name(tree, direct_module, repository_name)
        assert not _imports_name(tree, "app.services.persistence", repository_name)


def _imports_name(tree: ast.Module, module: str, name: str) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == name for alias in node.names)
        for node in ast.walk(tree)
    )
