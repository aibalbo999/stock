from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.services.api_compatibility_candidate import CandidateCompatibilityMixin
from app.services.api_compatibility_discovery import DiscoveryCompatibilityMixin
from app.services.api_compatibility_followup import FollowUpCompatibilityMixin
from app.services.api_compatibility_run_state import RunStateCompatibilityMixin


class ApiCompatibilityService(
    CandidateCompatibilityMixin,
    DiscoveryCompatibilityMixin,
    FollowUpCompatibilityMixin,
    RunStateCompatibilityMixin,
):
    """Compatibility boundary for legacy app.api.main helper imports.

    FastAPI routers call use-case services directly. A few tests, scripts, and
    factory hooks still import historical helper functions from app.api.main, so
    this service keeps that delegation outside the API entry module.
    """

    def __init__(
        self,
        *,
        api_services: Any,
        candidate_revalidation_module: Any,
        follow_up_run_request_cls: Callable[[], Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.api_services = api_services
        self.candidate_revalidation_module = candidate_revalidation_module
        self.follow_up_run_request_cls = follow_up_run_request_cls
        self.logger = logger or logging.getLogger(__name__)

    def _default_follow_up_run_request(self) -> Any:
        if self.follow_up_run_request_cls is None:
            raise RuntimeError("follow_up_run_request_cls is required when payload is omitted")
        return self.follow_up_run_request_cls()
