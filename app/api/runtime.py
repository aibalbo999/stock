from __future__ import annotations

import logging
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from app.api.compatibility_exports import compatibility_export_namespace
from app.api.compatibility_helpers import compatibility_helper_namespace
from app.api.dependencies import build_service_factory_dependencies
from app.api.service_factory import ApiServiceFactory
from app.api.task_exports import task_export_namespace
from app.services.api_compatibility import ApiCompatibilityService


LOGGER = logging.getLogger(__name__)


@dataclass
class ApiRuntime:
    api_services: ApiServiceFactory
    api_compatibility: ApiCompatibilityService
    compatibility_exports: dict[str, object]
    compatibility_helpers: dict[str, object]
    task_exports: dict[str, object]
    namespace: MutableMapping[str, Any]


def build_api_runtime(
    namespace: MutableMapping[str, Any] | None = None,
    *,
    logger: logging.Logger | None = None,
) -> ApiRuntime:
    runtime_namespace: MutableMapping[str, Any] = namespace if namespace is not None else {}
    compatibility_exports = compatibility_export_namespace()
    runtime_namespace.update(compatibility_exports)
    task_exports = task_export_namespace()
    runtime_namespace.update(task_exports)
    compatibility_helpers = compatibility_helper_namespace(
        lambda: runtime_namespace["_api_compatibility"],
        globals_provider=lambda: runtime_namespace,
    )
    runtime_namespace.update(compatibility_helpers)

    runtime_logger = logger or LOGGER
    api_services = ApiServiceFactory(
        build_service_factory_dependencies(runtime_namespace),
        logger=runtime_logger,
    )
    api_compatibility = ApiCompatibilityService(
        api_services=api_services,
        candidate_revalidation_module=runtime_namespace["candidate_revalidation"],
        follow_up_run_request_cls=runtime_namespace["FollowUpRunRequest"],
        logger=runtime_logger,
    )
    runtime_namespace["_api_services"] = api_services
    runtime_namespace["_api_compatibility"] = api_compatibility
    return ApiRuntime(
        api_services=api_services,
        api_compatibility=api_compatibility,
        compatibility_exports=compatibility_exports,
        compatibility_helpers=compatibility_helpers,
        task_exports=task_exports,
        namespace=runtime_namespace,
    )


_task_api_runtime: ApiRuntime | None = None


def get_task_api_runtime() -> ApiRuntime:
    global _task_api_runtime
    if _task_api_runtime is None:
        _task_api_runtime = build_api_runtime()
    return _task_api_runtime


def get_task_api_services() -> ApiServiceFactory:
    return get_task_api_runtime().api_services
