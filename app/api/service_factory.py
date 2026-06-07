from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

from app.api.service_factory_data import DataServiceFactoryMixin
from app.api.service_factory_report import ReportServiceFactoryMixin
from app.api.service_factory_workflow import WorkflowServiceFactoryMixin


class ApiServiceFactory(DataServiceFactoryMixin, ReportServiceFactoryMixin, WorkflowServiceFactoryMixin):
    """Build API use-case services from the current application dependency namespace."""

    def __init__(self, dependencies: MutableMapping[str, Any], logger: logging.Logger | None = None) -> None:
        self.dependencies = dependencies
        self.logger = logger or logging.getLogger(__name__)

    def supply_chain_graph_api(self):
        d = self.dependencies
        return d["SupplyChainGraphApiService"](
            whitelist_cls=d["SupplyChainWhitelist"],
            neo4j_import_service_factory=lambda: d["Neo4jGraphImportService"](
                settings_provider=d["get_settings"],
            ),
        )

    def llm_api(self):
        d = self.dependencies
        return d["LLMApiService"](
            llm_client_cls=d["LLMClient"],
            session_scope_factory=d["session_scope"],
            llm_usage_repository_cls=d["LLMUsageRepository"],
        )
