import ast
from pathlib import Path


ANALYSIS_RUN_CALLER_PATHS = (
    Path("app/services/run_task_api.py"),
    Path("app/services/task_cancellation.py"),
    Path("app/services/workflow_checkpoint.py"),
    Path("app/db/status.py"),
    Path("app/services/report_generation_api.py"),
    Path("app/services/report_query.py"),
    Path("app/services/report_followup_context.py"),
    Path("app/services/data_operations_api.py"),
    Path("app/tasks/tasks.py"),
)


def test_analysis_run_callers_import_repository_directly() -> None:
    for path in ANALYSIS_RUN_CALLER_PATHS:
        tree = ast.parse(path.read_text())

        assert _imports_name(tree, "app.services.analysis_run_repository", "AnalysisRunRepository")
        assert not _imports_name(tree, "app.services.persistence", "AnalysisRunRepository")


def _imports_name(tree: ast.Module, module: str, name: str) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == name for alias in node.names)
        for node in ast.walk(tree)
    )
