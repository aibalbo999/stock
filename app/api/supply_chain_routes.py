from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import api_services_provider


def create_supply_chain_router(api_services: Any | None = None) -> APIRouter:
    router = APIRouter()
    services_dependency = api_services_provider(api_services)

    @router.get("/whitelist")
    def whitelist(services: Any = Depends(services_dependency)) -> dict:
        return services.supply_chain_graph_api().whitelist_payload()

    @router.get("/supply-chain/graph")
    def supply_chain_graph(
        tickers: str = "",
        topic: str = "",
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.supply_chain_graph_api().graph_payload(tickers, topic)

    @router.get("/supply-chain/graph/neo4j")
    def supply_chain_graph_neo4j(
        tickers: str = "",
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.supply_chain_graph_api().graph_neo4j_payload(tickers)

    @router.post("/supply-chain/graph/neo4j/import")
    def import_supply_chain_graph_neo4j(
        tickers: str = "",
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.supply_chain_graph_api().import_graph_to_neo4j(tickers)

    return router
