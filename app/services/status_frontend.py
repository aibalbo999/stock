from __future__ import annotations

from app.services.status_frontend_data_enrichment import (
    frontend_data_enrichment_status,
)
from app.services.status_frontend_external_deployment import (
    frontend_external_deployment_status,
)
from app.services.status_frontend_operator_workbench import (
    frontend_operator_workbench_status,
)
from app.services.status_frontend_reports import frontend_report_ui_status
from app.services.status_frontend_runtime import frontend_runtime_status
from app.services.status_frontend_settings import frontend_settings_ui_status
from app.services.status_frontend_sources import frontend_source_context
from app.services.status_frontend_submission_guards import (
    frontend_submission_guard_status,
)
from app.services.status_frontend_tasks import frontend_task_ui_status


def frontend_status() -> dict:
    source_context = frontend_source_context()
    streamlit_source = source_context.streamlit_source
    ui_paths = source_context.ui_paths
    ui_source = source_context.ui_source
    page_source = source_context.page_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    pages = source_context.pages
    streamlit_pages_source = source_context.streamlit_pages_source
    frontend_blocking_call_scan_paths = source_context.frontend_blocking_call_scan_paths
    status = {
        "collector_path": "app/services/status_frontend.py",
        "frontend_source_context_extracted": source_context.__class__.__name__
        == "FrontendSourceContext"
        and "dashboard_core.py" in ui_sources
        and "api_loaders.py" in ui_sources
        and "operator_decisions.py" in ui_sources
        and "data_gap_actions.py" in ui_sources
        and "maintenance_cleanup_panel.py" in ui_sources
        and bool(frontend_blocking_call_scan_paths),
        "frontend_source_context_path": "app/services/status_frontend_sources.py",
        "streamlit_app_lines": len(streamlit_source.splitlines()) if streamlit_source else None,
        "streamlit_entry_uses_navigation": "st.navigation" in streamlit_source
        and "st.Page" in streamlit_source,
        "page_count": len(pages),
        "pages": pages,
        "expected_pages_present": all(
            page in pages
            for page in [
                "01_分析工作區.py",
                "02_報告中心.py",
                "03_資料補強.py",
                "04_系統設定.py",
            ]
        ),
        "streamlit_page_import_contract_ready": (
            "from app.ui.dashboard_core import configure_page" in ui_source
            and "from app.ui.streamlit_dashboard import configure_page" in streamlit_pages_source
            and "render_analysis_workspace" in streamlit_pages_source
            and "render_report_center" in streamlit_pages_source
            and "render_data_enrichment" in streamlit_pages_source
            and "render_system_settings" in streamlit_pages_source
        ),
        "ui_modules_present": [path.name for path in ui_paths if path.exists()],
        "ui_wildcard_imports_removed": "import *" not in page_source
        and "F403" not in page_source
        and "F405" not in page_source,
        "dashboard_core_lines": len(dashboard_core_source.splitlines())
        if dashboard_core_source
        else None,
        **frontend_operator_workbench_status(source_context),
        **frontend_report_ui_status(source_context),
        **frontend_settings_ui_status(source_context),
        **frontend_task_ui_status(source_context),
        **frontend_external_deployment_status(source_context),
        **frontend_data_enrichment_status(source_context),
        **frontend_runtime_status(source_context),
    }
    status.update(frontend_submission_guard_status(status))
    return status
