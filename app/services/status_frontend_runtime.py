from __future__ import annotations

from app.services.status_frontend_sources import FrontendSourceContext


ASYNC_TASK_ENDPOINTS = [
    "/pipeline/run_discovered_async",
    "/reports/generate_async",
    "/tasks/data-operation",
    "/tasks/maintenance-operation/",
    "/tasks/maintenance-diagnostic/",
    "/follow-up/run_async",
]


def frontend_runtime_status(source_context: FrontendSourceContext) -> dict:
    root = source_context.root
    style_path = source_context.style_path
    style_source = _read_text(style_path)
    ui_source = source_context.ui_source
    dashboard_core_source = source_context.ui_sources["dashboard_core.py"]
    frontend_smoke_source = _read_text(root / "app" / "services" / "frontend_smoke.py")
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
        "ui_streamlit_operator_chrome_hidden": (
            '[data-testid="stToolbar"]' in style_source
            and '[data-testid="stDecoration"]' in style_source
            and '[data-testid="stStatusWidget"]' in style_source
            and '[data-testid="stSidebarCollapseButton"]' in style_source
            and ".stDeployButton" in style_source
            and "display: none !important" in style_source
            and "pointer-events: none !important" in style_source
        ),
        "ui_touch_targets_min_size_enabled": (
            'button[data-testid^="stBaseButton"] {\n    min-height: 48px !important;'
            in style_source
            and 'button[data-testid="stBaseButton-elementToolbar"]' in style_source
            and style_source.count('button[data-testid="stBaseButton-elementToolbar"]') == 3
            and 'button[data-testid="stNumberInputStepDown"]' in style_source
            and 'button[data-testid="stNumberInputStepUp"]' in style_source
            and "min-height: 44px !important" in style_source
            and "min-height: 40px !important" not in style_source
        ),
        "ui_sidebar_nav_touch_targets_min_size_enabled": (
            '[data-testid="stSidebarNavLink"] {\n    min-height: 44px !important;'
            in style_source
            and "align-items: center !important" in style_source
            and "touch-action: manipulation" in style_source
            and '[data-testid="stSidebarNavLink"]:focus-visible' in style_source
        ),
        "ui_selectbox_touch_targets_min_size_enabled": (
            '[data-baseweb="select"] > div {\n    min-height: 44px !important;'
            in style_source
            and '[data-baseweb="select"] svg[role="button"]' in style_source
            and "touch-action: manipulation" in style_source
            and "min-height: 40px !important" not in style_source
        ),
        "ui_form_input_touch_targets_min_size_enabled": (
            '[data-baseweb="input"] {\n    min-height: 44px !important;' in style_source
            and '[data-baseweb="base-input"],' in style_source
            and '[data-testid="stTextInputRootElement"],' in style_source
            and '[data-testid="stDateInput"] [data-baseweb="input"],' in style_source
            and '[data-testid="stNumberInput"] [data-baseweb="input"] {' in style_source
            and '[data-testid="stDateInputField"],' in style_source
            and '[data-testid="stNumberInputField"],' in style_source
            and "min-height: 40px !important" not in style_source
        ),
        "ui_streamlit_heading_anchor_noise_hidden": (
            'a[aria-label="Link to heading"]' in style_source
            and "display: none !important" in style_source
            and "visibility: hidden !important" in style_source
            and "pointer-events: none !important" in style_source
        ),
        "frontend_runtime_identity_marker_enabled": (
            'data-stock-frontend-runtime="true"' in dashboard_core_source
            and "runtime_identity_status()" in dashboard_core_source
            and "render_frontend_runtime_identity()" in dashboard_core_source
        ),
        "frontend_runtime_identity_marker_path": "app/ui/dashboard_core.py",
        "frontend_smoke_checks_runtime_identity_marker": (
            "frontend_runtime_identity_result(" in frontend_smoke_source
            and "data-stock-frontend-runtime" in frontend_smoke_source
            and "streamlit_runtime_commit_mismatch" in frontend_smoke_source
        ),
        "frontend_runtime_identity_smoke_path": "app/services/frontend_smoke.py",
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


def _read_text(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
