from __future__ import annotations

from pathlib import Path


DASHBOARD_SOURCE = Path("app/ui/streamlit_dashboard.py")
DASHBOARD_CORE_SOURCE = Path("app/ui/dashboard_core.py")
API_CLIENT_SOURCE = Path("app/ui/api_client.py")
API_LOADERS_SOURCE = Path("app/ui/api_loaders.py")
BACKGROUND_TASKS_SOURCE = Path("app/ui/background_tasks.py")
TASK_STATUS_PANEL_SOURCE = Path("app/ui/task_status_panel.py")
TASK_STATUS_PRESENTER_SOURCE = Path("app/ui/task_status_presenter.py")
TASK_STATUS_VIEW_SOURCE = Path("app/ui/task_status_view.py")
REPORT_STATE_SOURCE = Path("app/ui/report_state.py")
REPORT_PANELS_SOURCE = Path("app/ui/report_panels.py")
REPORT_FOLLOW_UP_CONTROLS_SOURCE = Path("app/ui/report_follow_up_controls.py")
REPORT_MARKDOWN_SOURCE = Path("app/ui/report_markdown.py")
REPORT_CANDIDATE_AUDIT_SOURCE = Path("app/ui/report_candidate_audit.py")
REPORT_FORMATTERS_SOURCE = Path("app/ui/report_formatters.py")
REPORT_SECTIONS_SOURCE = Path("app/ui/report_sections.py")
REPORT_HTML_SOURCE = Path("app/ui/report_html.py")
OPERATOR_STATUS_SOURCE = Path("app/ui/operator_status.py")
OPERATOR_OPTIMIZATION_ACTIONS_SOURCE = Path("app/ui/operator_optimization_actions.py")
OPERATOR_TASK_STATE_SOURCE = Path("app/ui/operator_task_state.py")
OPERATOR_ROUTES_SOURCE = Path("app/ui/operator_routes.py")
OPERATOR_ROUTE_CONTROLS_SOURCE = Path("app/ui/operator_route_controls.py")
REPORT_HEALTH_SOURCE = Path("app/ui/report_health.py")
REPORT_LIFECYCLE_SOURCE = Path("app/ui/report_lifecycle.py")
REPORT_CENTER_PRESENTER_SOURCE = Path("app/ui/report_center_presenter.py")
INCIDENT_INBOX_SOURCE = Path("app/ui/incident_inbox.py")
OPERATOR_DECISIONS_SOURCE = Path("app/ui/operator_decisions.py")
OPERATOR_DECISION_SUPPORT_SOURCE = Path("app/ui/operator_decision_support.py")
DATA_GAP_ACTIONS_SOURCE = Path("app/ui/data_gap_actions.py")
DATA_ENRICHMENT_MANUAL_PRESENTER_SOURCE = Path("app/ui/data_enrichment_manual_presenter.py")
DATA_ENRICHMENT_MARKET_PRESENTER_SOURCE = Path("app/ui/data_enrichment_market_presenter.py")
FOLLOW_UP_STATUS_SOURCE = Path("app/ui/follow_up_status.py")
MAINTENANCE_STATUS_SOURCE = Path("app/ui/maintenance_status.py")
MAINTENANCE_PROGRESS_PRESENTER_SOURCE = Path("app/ui/maintenance_progress_presenter.py")
MAINTENANCE_PANELS_SOURCE = Path("app/ui/maintenance_panels.py")
MAINTENANCE_DEPLOYMENT_PANEL_SOURCE = Path("app/ui/maintenance_deployment_panel.py")
MAINTENANCE_DEPLOYMENT_PRESENTER_SOURCE = Path("app/ui/maintenance_deployment_presenter.py")
MAINTENANCE_AI_PANELS_SOURCE = Path("app/ui/maintenance_ai_panels.py")
MAINTENANCE_TASK_PANELS_SOURCE = Path("app/ui/maintenance_task_panels.py")
MAINTENANCE_CLEANUP_PANEL_SOURCE = Path("app/ui/maintenance_cleanup_panel.py")
REPORT_OBSERVABILITY_PANEL_SOURCE = Path("app/ui/report_observability_panel.py")
EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE = Path("app/ui/external_deployment_diagnostics.py")
EXTERNAL_DEPLOYMENT_COMMON_SOURCE = Path("app/ui/external_deployment_common.py")
EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE = Path("app/ui/external_deployment_env_keys.py")
EXTERNAL_DEPLOYMENT_UNLOCKER_SOURCE = Path("app/ui/external_deployment_unlocker.py")
EXTERNAL_DEPLOYMENT_NEO4J_SOURCE = Path("app/ui/external_deployment_neo4j.py")
EXTERNAL_DEPLOYMENT_STRUCTURED_API_SOURCE = Path("app/ui/external_deployment_structured_api.py")
TASK_QUEUE_DIAGNOSTICS_SOURCE = Path("app/ui/task_queue_diagnostics.py")
TASK_FAILURE_DIAGNOSTICS_SOURCE = Path("app/ui/task_failure_diagnostics.py")
ANALYSIS_WORKSPACE_PRESENTER_SOURCE = Path("app/ui/analysis_workspace_presenter.py")
SYSTEM_SETTINGS_SOURCE = Path("app/ui/system_settings.py")
SYSTEM_SETTINGS_SCOPE_SOURCE = Path("app/ui/system_settings_scope.py")
SYSTEM_SETTINGS_SCHEDULE_SOURCE = Path("app/ui/system_settings_schedule.py")
UI_SOURCE_FILES = [
    DASHBOARD_SOURCE,
    DASHBOARD_CORE_SOURCE,
    API_CLIENT_SOURCE,
    API_LOADERS_SOURCE,
    BACKGROUND_TASKS_SOURCE,
    TASK_STATUS_PANEL_SOURCE,
    TASK_STATUS_PRESENTER_SOURCE,
    TASK_STATUS_VIEW_SOURCE,
    REPORT_STATE_SOURCE,
    REPORT_PANELS_SOURCE,
    REPORT_FOLLOW_UP_CONTROLS_SOURCE,
    REPORT_MARKDOWN_SOURCE,
    REPORT_CANDIDATE_AUDIT_SOURCE,
    REPORT_FORMATTERS_SOURCE,
    REPORT_SECTIONS_SOURCE,
    REPORT_HTML_SOURCE,
    OPERATOR_STATUS_SOURCE,
    OPERATOR_OPTIMIZATION_ACTIONS_SOURCE,
    OPERATOR_TASK_STATE_SOURCE,
    OPERATOR_ROUTES_SOURCE,
    OPERATOR_ROUTE_CONTROLS_SOURCE,
    REPORT_HEALTH_SOURCE,
    REPORT_LIFECYCLE_SOURCE,
    REPORT_CENTER_PRESENTER_SOURCE,
    INCIDENT_INBOX_SOURCE,
    OPERATOR_DECISIONS_SOURCE,
    OPERATOR_DECISION_SUPPORT_SOURCE,
    DATA_GAP_ACTIONS_SOURCE,
    FOLLOW_UP_STATUS_SOURCE,
    MAINTENANCE_STATUS_SOURCE,
    MAINTENANCE_PROGRESS_PRESENTER_SOURCE,
    MAINTENANCE_PANELS_SOURCE,
    MAINTENANCE_DEPLOYMENT_PANEL_SOURCE,
    MAINTENANCE_DEPLOYMENT_PRESENTER_SOURCE,
    MAINTENANCE_AI_PANELS_SOURCE,
    MAINTENANCE_TASK_PANELS_SOURCE,
    MAINTENANCE_CLEANUP_PANEL_SOURCE,
    REPORT_OBSERVABILITY_PANEL_SOURCE,
    EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE,
    EXTERNAL_DEPLOYMENT_COMMON_SOURCE,
    EXTERNAL_DEPLOYMENT_ENV_KEYS_SOURCE,
    EXTERNAL_DEPLOYMENT_UNLOCKER_SOURCE,
    EXTERNAL_DEPLOYMENT_NEO4J_SOURCE,
    EXTERNAL_DEPLOYMENT_STRUCTURED_API_SOURCE,
    TASK_QUEUE_DIAGNOSTICS_SOURCE,
    TASK_FAILURE_DIAGNOSTICS_SOURCE,
    ANALYSIS_WORKSPACE_PRESENTER_SOURCE,
    Path("app/ui/analysis_workspace.py"),
    Path("app/ui/report_center.py"),
    Path("app/ui/data_enrichment.py"),
    Path("app/ui/data_enrichment_common.py"),
    Path("app/ui/data_enrichment_manual.py"),
    DATA_ENRICHMENT_MANUAL_PRESENTER_SOURCE,
    Path("app/ui/data_enrichment_market.py"),
    DATA_ENRICHMENT_MARKET_PRESENTER_SOURCE,
    Path("app/ui/data_enrichment_rss.py"),
    Path("app/ui/data_enrichment_runtime.py"),
    SYSTEM_SETTINGS_SOURCE,
    SYSTEM_SETTINGS_SCOPE_SOURCE,
    SYSTEM_SETTINGS_SCHEDULE_SOURCE,
    Path("app/ui/system_settings_maintenance.py"),
]
STYLE_SOURCE = Path("app/ui/styles/stock_dashboard.css")
REPORT_STYLE_SOURCE = Path("app/ui/styles/report_html.css")


def read_ui_source() -> str:
    return "\n".join(path.read_text() for path in UI_SOURCE_FILES)


def load_report_helpers() -> dict:
    candidate_audit_source = REPORT_CANDIDATE_AUDIT_SOURCE.read_text()
    report_source = REPORT_HTML_SOURCE.read_text()
    follow_up_source = FOLLOW_UP_STATUS_SOURCE.read_text()
    maintenance_source = MAINTENANCE_STATUS_SOURCE.read_text()
    external_deployment_source = EXTERNAL_DEPLOYMENT_DIAGNOSTICS_SOURCE.read_text()
    task_queue_diagnostics_source = TASK_QUEUE_DIAGNOSTICS_SOURCE.read_text()
    task_failure_diagnostics_source = TASK_FAILURE_DIAGNOSTICS_SOURCE.read_text()
    namespace = {
        "__file__": str(REPORT_CANDIDATE_AUDIT_SOURCE),
    }
    exec(candidate_audit_source, namespace)
    namespace["__file__"] = str(REPORT_HTML_SOURCE)
    exec(report_source, namespace)
    exec(follow_up_source, namespace)
    exec(task_queue_diagnostics_source, namespace)
    exec(task_failure_diagnostics_source, namespace)
    exec(maintenance_source, namespace)
    exec(external_deployment_source, namespace)
    return namespace
