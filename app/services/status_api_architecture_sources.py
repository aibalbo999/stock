from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LEGACY_FACADE_REFERENCE_LITERALS = (
    "LegacyApiFacade",
    "app.api.legacy_facade",
    "_legacy_api",
)


@dataclass(frozen=True)
class ApiArchitectureSourceContext:
    root: Path
    app_dir: Path
    api_dir: Path
    paths: dict[str, Path]
    sources: dict[str, str]
    route_modules: list[str]
    api_python_paths: list[Path]
    legacy_facade_reference_scan_paths: list[Path]
    legacy_facade_api_reference_locations: list[dict[str, int | str]]


def api_architecture_source_context() -> ApiArchitectureSourceContext:
    app_dir = Path(__file__).resolve().parents[1]
    root = app_dir.parent
    api_dir = app_dir / "api"
    paths = {
        "main": api_dir / "main.py",
        "service_factory": api_dir / "service_factory.py",
        "runtime": api_dir / "runtime.py",
        "operations_routes": api_dir / "operations_routes.py",
        "operation_task_submission": api_dir / "operation_task_submission.py",
        "report_routes": api_dir / "report_routes.py",
        "error_details": api_dir / "error_details.py",
        "task_submission_errors": api_dir / "task_submission_errors.py",
        "legacy_facade": api_dir / "legacy_facade.py",
        "compatibility_exports": api_dir / "compatibility_exports.py",
        "compatibility_export_core": api_dir / "compatibility_export_core.py",
        "compatibility_export_data": api_dir / "compatibility_export_data.py",
        "compatibility_export_discovery": api_dir / "compatibility_export_discovery.py",
        "compatibility_export_report": api_dir / "compatibility_export_report.py",
        "compatibility_export_workflow": api_dir / "compatibility_export_workflow.py",
        "compatibility_helpers": api_dir / "compatibility_helpers.py",
        "compatibility_helper_candidate": api_dir / "compatibility_helper_candidate.py",
        "compatibility_helper_discovery": api_dir / "compatibility_helper_discovery.py",
        "compatibility_helper_followup": api_dir / "compatibility_helper_followup.py",
        "compatibility_helper_run_state": api_dir / "compatibility_helper_run_state.py",
        "task_exports": api_dir / "task_exports.py",
        "report_service_factory": api_dir / "service_factory_report.py",
        "data_service_factory": api_dir / "service_factory_data.py",
        "workflow_service_factory": api_dir / "service_factory_workflow.py",
        "ai_graph_service_factory": api_dir / "service_factory_ai.py",
        "tasks": app_dir / "tasks" / "tasks.py",
        "run_task_api": app_dir / "services" / "run_task_api.py",
        "persistence": app_dir / "services" / "persistence.py",
        "task_failure_diagnostics": app_dir / "services" / "task_failure_diagnostics.py",
        "config": app_dir / "core" / "config.py",
        "report_generation_api": app_dir / "services" / "report_generation_api.py",
        "api_compatibility": app_dir / "services" / "api_compatibility.py",
        "compatibility_candidate": app_dir / "services" / "api_compatibility_candidate.py",
        "compatibility_discovery": app_dir / "services" / "api_compatibility_discovery.py",
        "compatibility_followup": app_dir / "services" / "api_compatibility_followup.py",
        "compatibility_run_state": app_dir / "services" / "api_compatibility_run_state.py",
    }
    sources = {name: _read_source(path) for name, path in paths.items()}
    api_python_paths = sorted(api_dir.glob("*.py")) if api_dir.exists() else []
    legacy_facade_reference_scan_paths = [
        path for path in api_python_paths if path != paths["legacy_facade"]
    ]
    legacy_facade_api_reference_locations = _literal_occurrence_locations(
        legacy_facade_reference_scan_paths,
        LEGACY_FACADE_REFERENCE_LITERALS,
        root=root,
    )
    return ApiArchitectureSourceContext(
        root=root,
        app_dir=app_dir,
        api_dir=api_dir,
        paths=paths,
        sources=sources,
        route_modules=sorted(path.name for path in api_dir.glob("*_routes.py")),
        api_python_paths=api_python_paths,
        legacy_facade_reference_scan_paths=legacy_facade_reference_scan_paths,
        legacy_facade_api_reference_locations=legacy_facade_api_reference_locations,
    )


def _literal_occurrence_locations(
    paths: list[Path],
    literals: tuple[str, ...],
    *,
    root: Path,
) -> list[dict[str, int | str]]:
    locations: list[dict[str, int | str]] = []
    for path in paths:
        source = _read_source(path)
        for literal in literals:
            count = source.count(literal)
            if count:
                locations.append(
                    {
                        "path": str(path.relative_to(root)),
                        "literal": literal,
                        "count": count,
                    }
                )
    return locations


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
