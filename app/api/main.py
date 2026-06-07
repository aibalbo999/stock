from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from app.api.app_factory import create_app
from app.api.compatibility_helpers import (
    LEGACY_DELEGATE_EXPORT_NAMES,
)
from app.api.compatibility_exports import (
    COMPATIBILITY_EXPORT_NAMES,
    LEGACY_HELPER_EXPORT_NAMES,
)
from app.api.runtime import build_api_runtime
from app.api.task_exports import TASK_EXPORT_NAMES


LOGGER = logging.getLogger(__name__)

_api_runtime = build_api_runtime(globals(), logger=LOGGER)
_compatibility_exports = _api_runtime.compatibility_exports
init_db = _compatibility_exports["init_db"]
candidate_revalidation = _compatibility_exports["candidate_revalidation"]
FollowUpRunRequest = _compatibility_exports["FollowUpRunRequest"]

__all__ = [
    *LEGACY_HELPER_EXPORT_NAMES,
    *LEGACY_DELEGATE_EXPORT_NAMES,
    "app",
    "_api_services",
]

_compatibility_helpers = _api_runtime.compatibility_helpers
get_report_follow_up_plan = _compatibility_helpers["get_report_follow_up_plan"]
maybe_auto_start_required_follow_up = _compatibility_helpers["maybe_auto_start_required_follow_up"]
run_report_follow_up = _compatibility_helpers["run_report_follow_up"]


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


_api_services = _api_runtime.api_services
_api_compatibility = _api_runtime.api_compatibility

app = create_app(
    api_services=_api_services,
    lifespan=lifespan,
    get_follow_up_plan_func=get_report_follow_up_plan,
    auto_start_follow_up_func=lambda report_id: maybe_auto_start_required_follow_up(report_id),
    run_follow_up_func=lambda report_id, payload=None: run_report_follow_up(report_id, payload),
)


def __dir__() -> list[str]:
    return sorted({*globals(), *COMPATIBILITY_EXPORT_NAMES, *TASK_EXPORT_NAMES})
