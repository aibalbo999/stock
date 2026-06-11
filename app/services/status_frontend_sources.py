from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

UI_MODULE_NAMES = (
    "dashboard_core.py",
    "api_client.py",
    "api_loaders.py",
    "background_tasks.py",
    "task_status_panel.py",
    "task_status_presenter.py",
    "task_status_view.py",
    "report_state.py",
    "report_panels.py",
    "report_follow_up_controls.py",
    "report_markdown.py",
    "report_candidate_audit.py",
    "report_formatters.py",
    "report_sections.py",
    "report_html.py",
    "report_follow_up_presenter.py",
    "follow_up_status.py",
    "llm_quota_panel.py",
    "operator_status.py",
    "operator_quota_presenter.py",
    "operator_optimization_actions.py",
    "operator_task_state.py",
    "operator_routes.py",
    "operator_route_controls.py",
    "operator_decisions.py",
    "operator_decision_support.py",
    "report_health.py",
    "report_lifecycle.py",
    "report_center_presenter.py",
    "report_center_view.py",
    "report_center_history.py",
    "incident_inbox.py",
    "data_gap_actions.py",
    "report_observability_panel.py",
    "external_deployment_diagnostics.py",
    "external_deployment_common.py",
    "external_deployment_env_keys.py",
    "external_deployment_unlocker.py",
    "external_deployment_neo4j.py",
    "external_deployment_structured_api.py",
    "task_queue_diagnostics.py",
    "task_failure_diagnostics.py",
    "analysis_operator_presenter.py",
    "analysis_task_lookup_panel.py",
    "maintenance_incident_presenter.py",
    "maintenance_incident_view.py",
    "maintenance_status.py",
    "maintenance_progress_presenter.py",
    "maintenance_progress_view.py",
    "analysis_workspace_presenter.py",
    "analysis_workspace.py",
    "analysis_task_lookup_panel.py",
    "analysis_workspace_view.py",
    "report_center.py",
    "data_enrichment.py",
    "data_enrichment_common.py",
    "data_enrichment_common_view.py",
    "data_enrichment_manual.py",
    "data_enrichment_manual_presenter.py",
    "data_enrichment_market.py",
    "data_enrichment_market_cache.py",
    "data_enrichment_market_presenter.py",
    "data_enrichment_market_view.py",
    "data_enrichment_rss.py",
    "data_enrichment_runtime.py",
    "system_settings.py",
    "system_settings_scope.py",
    "system_settings_scope_view.py",
    "system_settings_schedule.py",
    "system_settings_maintenance.py",
    "maintenance_incident_presenter.py",
    "maintenance_panels.py",
    "maintenance_deployment_panel.py",
    "maintenance_deployment_presenter.py",
    "maintenance_deployment_view.py",
    "maintenance_operation_controls.py",
    "maintenance_ai_panels.py",
    "maintenance_task_panels.py",
    "maintenance_cleanup_panel.py",
    "streamlit_dashboard.py",
)

PAGE_UI_MODULE_NAMES = (
    "analysis_workspace.py",
    "analysis_task_lookup_panel.py",
    "analysis_workspace_view.py",
    "report_center.py",
    "report_center_view.py",
    "report_center_history.py",
    "data_enrichment.py",
    "data_enrichment_common.py",
    "data_enrichment_common_view.py",
    "data_enrichment_manual.py",
    "data_enrichment_market.py",
    "data_enrichment_market_cache.py",
    "data_enrichment_market_view.py",
    "data_enrichment_rss.py",
    "data_enrichment_runtime.py",
    "system_settings.py",
    "system_settings_scope.py",
    "system_settings_scope_view.py",
    "system_settings_schedule.py",
    "system_settings_maintenance.py",
    "maintenance_incident_view.py",
    "maintenance_progress_view.py",
    "maintenance_panels.py",
    "maintenance_deployment_panel.py",
    "maintenance_deployment_presenter.py",
    "maintenance_deployment_view.py",
    "maintenance_operation_controls.py",
    "maintenance_ai_panels.py",
    "maintenance_task_panels.py",
    "maintenance_cleanup_panel.py",
    "streamlit_dashboard.py",
)

DATA_ENRICHMENT_MODULE_NAMES = (
    "data_enrichment.py",
    "data_enrichment_common.py",
    "data_enrichment_common_view.py",
    "data_enrichment_manual.py",
    "data_enrichment_manual_presenter.py",
    "data_enrichment_market.py",
    "data_enrichment_market_cache.py",
    "data_enrichment_market_presenter.py",
    "data_enrichment_market_view.py",
    "data_enrichment_rss.py",
    "data_enrichment_runtime.py",
)


@dataclass(frozen=True)
class FrontendSourceContext:
    root: Path
    streamlit_path: Path
    pages_dir: Path
    ui_dir: Path
    style_path: Path
    report_style_path: Path
    streamlit_source: str
    ui_paths: list[Path]
    ui_source: str
    page_source: str
    ui_sources: dict[str, str]
    data_enrichment_source: str
    pages: list[str]
    streamlit_pages_source: str
    frontend_blocking_call_scan_paths: list[Path]
    asyncio_run_locations: list[dict[str, int | str]]
    long_blocking_post_locations: list[dict[str, int | str]]


def frontend_source_context() -> FrontendSourceContext:
    root = Path(__file__).resolve().parents[2]
    streamlit_path = root / "streamlit_app.py"
    pages_dir = root / "pages"
    ui_dir = root / "app" / "ui"
    style_path = ui_dir / "styles" / "stock_dashboard.css"
    report_style_path = ui_dir / "styles" / "report_html.css"
    ui_paths = [ui_dir / module_name for module_name in UI_MODULE_NAMES]
    ui_sources = {module_name: _read_text(ui_dir / module_name) for module_name in UI_MODULE_NAMES}
    ui_source = "\n".join(ui_sources[module_name] for module_name in UI_MODULE_NAMES)
    page_source = "\n".join(ui_sources[module_name] for module_name in PAGE_UI_MODULE_NAMES)
    data_enrichment_source = "\n".join(
        ui_sources[module_name] for module_name in DATA_ENRICHMENT_MODULE_NAMES
    )
    pages = sorted(path.name for path in pages_dir.glob("*.py")) if pages_dir.exists() else []
    streamlit_pages_source = "\n".join(_read_text(pages_dir / page_name) for page_name in pages)
    all_ui_python_paths = sorted(ui_dir.glob("*.py")) if ui_dir.exists() else []
    frontend_blocking_call_scan_paths = [
        streamlit_path,
        *[pages_dir / page_name for page_name in pages],
        *all_ui_python_paths,
    ]
    asyncio_run_locations = _literal_occurrence_locations(
        frontend_blocking_call_scan_paths,
        "asyncio.run",
        root=root,
    )
    long_blocking_post_locations = _literal_occurrence_locations(
        frontend_blocking_call_scan_paths,
        "timeout=900",
        root=root,
    )
    return FrontendSourceContext(
        root=root,
        streamlit_path=streamlit_path,
        pages_dir=pages_dir,
        ui_dir=ui_dir,
        style_path=style_path,
        report_style_path=report_style_path,
        streamlit_source=_read_text(streamlit_path),
        ui_paths=ui_paths,
        ui_source=ui_source,
        page_source=page_source,
        ui_sources=ui_sources,
        data_enrichment_source=data_enrichment_source,
        pages=pages,
        streamlit_pages_source=streamlit_pages_source,
        frontend_blocking_call_scan_paths=frontend_blocking_call_scan_paths,
        asyncio_run_locations=asyncio_run_locations,
        long_blocking_post_locations=long_blocking_post_locations,
    )


def _literal_occurrence_locations(
    paths: list[Path],
    literal: str,
    *,
    root: Path,
) -> list[dict[str, int | str]]:
    locations: list[dict[str, int | str]] = []
    for path in paths:
        source = _read_text(path)
        count = source.count(literal)
        if count:
            locations.append(
                {
                    "path": str(path.relative_to(root)),
                    "count": count,
                }
            )
    return locations


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
