from __future__ import annotations


class AiGraphServiceFactoryMixin:
    """AI, LLM, and GraphRAG service wiring for ApiServiceFactory."""

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
