from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_supply_chain_router(api_services: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/whitelist")
    def whitelist() -> dict:
        return api_services.supply_chain_graph_api().whitelist_payload()

    @router.get("/supply-chain/graph")
    def supply_chain_graph(tickers: str = "", topic: str = "") -> dict:
        return api_services.supply_chain_graph_api().graph_payload(tickers, topic)

    @router.get("/supply-chain/graph/neo4j")
    def supply_chain_graph_neo4j(tickers: str = "") -> dict:
        return api_services.supply_chain_graph_api().graph_neo4j_payload(tickers)

    @router.post("/supply-chain/graph/neo4j/import")
    def import_supply_chain_graph_neo4j(tickers: str = "") -> dict:
        return api_services.supply_chain_graph_api().import_graph_to_neo4j(tickers)

    return router
