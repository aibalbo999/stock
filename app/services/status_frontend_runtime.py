from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


ASYNC_TASK_ENDPOINTS = [
    "/pipeline/run_discovered_async",
    "/reports/generate_async",
    "/tasks/data-operation",
    "/follow-up/run_async",
]


def frontend_runtime_status(source_context: FrontendSourceContext) -> dict:
    root = source_context.root
    style_path = source_context.style_path
    ui_source = source_context.ui_source
    frontend_blocking_call_scan_paths = source_context.frontend_blocking_call_scan_paths
    asyncio_run_locations = source_context.asyncio_run_locations
    long_blocking_post_locations = source_context.long_blocking_post_locations
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
        "frontend_runtime_status_extracted": True,
        "frontend_runtime_status_path": "app/services/status_frontend_runtime.py",
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
            ui_source,
            "API_WRITE_TIMEOUT_SECONDS",
        ),
        "api_task_queue_timeout_seconds": _frontend_constant_value(
            ui_source,
            "API_TASK_QUEUE_TIMEOUT_SECONDS",
        ),
        "uses_task_enqueue_helper": "def api_task_post(" in ui_source,
        "async_task_endpoints": ASYNC_TASK_ENDPOINTS,
        "async_task_endpoint_coverage": {
            endpoint: endpoint in ui_source for endpoint in ASYNC_TASK_ENDPOINTS
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
