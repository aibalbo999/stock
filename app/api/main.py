from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from app.api.app_factory import create_app
from app.api.compatibility_helpers import (
    LEGACY_DELEGATE_EXPORT_NAMES,
    compatibility_helper_namespace,
)
from app.api.compatibility_exports import (
    COMPATIBILITY_EXPORT_NAMES,
    LEGACY_HELPER_EXPORT_NAMES,
    compatibility_export_namespace,
)
from app.api.dependencies import build_service_factory_dependencies
from app.api.service_factory import ApiServiceFactory
from app.services.api_compatibility import ApiCompatibilityService


LOGGER = logging.getLogger(__name__)

_compatibility_exports = compatibility_export_namespace()
globals().update(_compatibility_exports)
init_db = _compatibility_exports["init_db"]
candidate_revalidation = _compatibility_exports["candidate_revalidation"]
FollowUpRunRequest = _compatibility_exports["FollowUpRunRequest"]

__all__ = [
    *LEGACY_HELPER_EXPORT_NAMES,
    *LEGACY_DELEGATE_EXPORT_NAMES,
    "app",
    "_api_services",
]


_compatibility_helpers = compatibility_helper_namespace(
    lambda: _api_compatibility,
    globals_provider=lambda: globals(),
)
globals().update(_compatibility_helpers)
get_report_follow_up_plan = _compatibility_helpers["get_report_follow_up_plan"]
maybe_auto_start_required_follow_up = _compatibility_helpers["maybe_auto_start_required_follow_up"]
run_report_follow_up = _compatibility_helpers["run_report_follow_up"]


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


_api_services = ApiServiceFactory(build_service_factory_dependencies(globals()), logger=LOGGER)
_api_compatibility = ApiCompatibilityService(
    api_services=_api_services,
    candidate_revalidation_module=candidate_revalidation,
    follow_up_run_request_cls=FollowUpRunRequest,
    logger=LOGGER,
)

app = create_app(
    api_services=_api_services,
    lifespan=lifespan,
    get_follow_up_plan_func=get_report_follow_up_plan,
    auto_start_follow_up_func=lambda report_id: maybe_auto_start_required_follow_up(report_id),
    run_follow_up_func=lambda report_id, payload=None: run_report_follow_up(report_id, payload),
)


def __dir__() -> list[str]:
    return sorted({*globals(), *COMPATIBILITY_EXPORT_NAMES})
