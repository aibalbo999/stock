import ast
from pathlib import Path


REPORT_REPOSITORY_CALLER_PATHS = (
    Path("app/services/discovered_report_builder.py"),
    Path("app/services/report_followup_context.py"),
    Path("app/services/data_operations_api.py"),
    Path("app/tasks/tasks.py"),
    Path("app/services/report_generation_api.py"),
    Path("app/services/report_query.py"),
)


def test_report_callers_import_repository_directly() -> None:
    for path in REPORT_REPOSITORY_CALLER_PATHS:
        tree = ast.parse(path.read_text())

        assert _imports_name(tree, "app.services.report_repository", "ReportRepository")
        assert not _imports_name(tree, "app.services.persistence", "ReportRepository")


def _imports_name(tree: ast.Module, module: str, name: str) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == name for alias in node.names)
        for node in ast.walk(tree)
    )
