from __future__ import annotations

from app.services.status_api_architecture_compatibility import (
    api_compatibility_architecture_status,
)
from app.services.status_api_architecture_service_factory import (
    api_service_factory_architecture_status,
)
from app.services.status_api_architecture_sources import api_architecture_source_context
from app.services.status_api_architecture_tasking import api_tasking_architecture_status


def api_controller_status() -> dict:
    source_context = api_architecture_source_context()
    api_dir = source_context.api_dir
    paths = source_context.paths
    sources = source_context.sources
    runtime_path = paths["runtime"]
    main_source = sources["main"]
    main_py_lines = len(main_source.splitlines()) if main_source else None
    legacy_facade_reference_scan_paths = source_context.legacy_facade_reference_scan_paths
    route_modules = source_context.route_modules
    direct_domain_imports = [
        line.strip()
        for line in main_source.splitlines()
        if (
            line.startswith("from app.data_sources.")
            or line.startswith("from app.db.")
            or line.startswith("from app.models.")
            or line.startswith("from app.rag.")
            or line.startswith("from app.tasks.")
            or (
                line.startswith("from app.services.")
                and "app.services.api_compatibility" not in line
            )
        )
    ]
    return {
        "collector_path": "app/services/status_api_architecture.py",
        "api_source_context_extracted": source_context.__class__.__name__
        == "ApiArchitectureSourceContext"
        and "main" in sources
        and "legacy_facade" in sources
        and bool(legacy_facade_reference_scan_paths),
        "api_source_context_path": "app/services/status_api_architecture_sources.py",
        "main_py_lines": main_py_lines,
        "route_module_count": len(route_modules),
        "route_modules": route_modules,
        "app_factory_present": (api_dir / "app_factory.py").exists(),
        "main_uses_app_factory": "from app.api.app_factory import create_app" in main_source,
        **api_service_factory_architecture_status(source_context),
        "api_runtime_present": runtime_path.exists(),
        "main_uses_api_runtime": "build_api_runtime" in main_source,
        **api_compatibility_architecture_status(source_context),
        **api_tasking_architecture_status(source_context),
        "main_direct_domain_import_count": len(direct_domain_imports),
        "main_direct_domain_imports": direct_domain_imports,
    }
