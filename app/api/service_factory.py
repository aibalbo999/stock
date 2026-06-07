from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

from app.api.service_factory_ai import AiGraphServiceFactoryMixin
from app.api.service_factory_data import DataServiceFactoryMixin
from app.api.service_factory_report import ReportServiceFactoryMixin
from app.api.service_factory_workflow import WorkflowServiceFactoryMixin


class ApiServiceFactory(
    AiGraphServiceFactoryMixin,
    DataServiceFactoryMixin,
    ReportServiceFactoryMixin,
    WorkflowServiceFactoryMixin,
):
    """Build API use-case services from the current application dependency namespace."""

    def __init__(self, dependencies: MutableMapping[str, Any], logger: logging.Logger | None = None) -> None:
        self.dependencies = dependencies
        self.logger = logger or logging.getLogger(__name__)
