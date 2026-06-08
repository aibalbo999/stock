from __future__ import annotations

from app.services.status_frontend_data_enrichment import (
    frontend_data_enrichment_status,
)
from app.services.status_frontend_external_deployment import (
    frontend_external_deployment_status,
)
from app.services.status_frontend_reports import frontend_report_ui_status
from app.services.status_frontend_settings import frontend_settings_ui_status
from app.services.status_frontend_sources import frontend_source_context
from app.services.status_frontend_tasks import frontend_task_ui_status


def frontend_status() -> dict:
    source_context = frontend_source_context()
    root = source_context.root
    style_path = source_context.style_path
    streamlit_source = source_context.streamlit_source
    ui_paths = source_context.ui_paths
    ui_source = source_context.ui_source
    page_source = source_context.page_source
    ui_sources = source_context.ui_sources
    dashboard_core_source = ui_sources["dashboard_core.py"]
    pages = source_context.pages
    streamlit_pages_source = source_context.streamlit_pages_source
    frontend_blocking_call_scan_paths = source_context.frontend_blocking_call_scan_paths
    asyncio_run_locations = source_context.asyncio_run_locations
    long_blocking_post_locations = source_context.long_blocking_post_locations
    async_task_endpoints = [
        "/pipeline/run_discovered_async",
        "/reports/generate_async",
        "/tasks/data-operation",
        "/follow-up/run_async",
    ]
    sync_report_generate_used = any(
        pattern in ui_source
        for pattern in (
            'api_post("/reports/generate",',
            "api_post('/reports/generate',",
            'api_task_post("/reports/generate",',
            "api_task_post('/reports/generate',",
        )
    )
    return {
        "collector_path": "app/services/status_frontend.py",
        "frontend_source_context_extracted": source_context.__class__.__name__
        == "FrontendSourceContext"
        and "dashboard_core.py" in ui_sources
        and "api_loaders.py" in ui_sources
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
        **frontend_report_ui_status(source_context),
        **frontend_settings_ui_status(source_context),
        **frontend_task_ui_status(source_context),
        **frontend_external_deployment_status(source_context),
        **frontend_data_enrichment_status(source_context),
        "external_css_path": str(style_path.relative_to(root)),
        "external_css_loaded": style_path.exists()
        and "STYLE_PATH.read_text" in ui_source
        and "unsafe_allow_html=True" in ui_source,
        "frontend_blocking_call_scan_paths": [
            str(path.relative_to(root)) for path in frontend_blocking_call_scan_paths
        ],
        "frontend_blocking_call_scan_file_count": len(frontend_blocking_call_scan_paths),
        "asyncio_run_count": sum(item["count"] for item in asyncio_run_locations),
        "asyncio_run_locations": asyncio_run_locations,
        "long_blocking_post_timeout_present": bool(long_blocking_post_locations),
        "long_blocking_post_timeout_locations": long_blocking_post_locations,
        "api_write_timeout_seconds": _frontend_constant_value(
            ui_source, "API_WRITE_TIMEOUT_SECONDS"
        ),
        "api_task_queue_timeout_seconds": _frontend_constant_value(
            ui_source,
            "API_TASK_QUEUE_TIMEOUT_SECONDS",
        ),
        "uses_task_enqueue_helper": "def api_task_post(" in ui_source,
        "async_task_endpoints": async_task_endpoints,
        "async_task_endpoint_coverage": {
            endpoint: endpoint in ui_source for endpoint in async_task_endpoints
        },
        "sync_report_generate_used": sync_report_generate_used,
        "data_operation_endpoint_used": "/tasks/data-operation" in ui_source,
    }


def _frontend_constant_value(source: str, name: str) -> int | None:
    prefix = f"{name} = "
    for line in source.splitlines():
        if line.startswith(prefix):
            try:
                return int(line.removeprefix(prefix).strip())
            except ValueError:
                return None
    return None
