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

    @router.get("/supply-chain/graph/reasoning")
    def supply_chain_graph_reasoning(
        tickers: str = "",
        target_ticker: str = "",
        topic: str = "",
        max_depth: int = 3,
        max_paths: int = 8,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.supply_chain_graph_api().graph_reasoning_payload(
            tickers,
            target_ticker=target_ticker,
            topic=topic,
            max_depth=max_depth,
            max_paths=max_paths,
        )

    @router.get("/supply-chain/graph/cypher-plan")
    def supply_chain_graph_cypher_plan(
        tickers: str = "",
        target_ticker: str = "",
        topic: str = "",
        question: str = "",
        max_depth: int = 3,
        use_llm: bool = False,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.supply_chain_graph_api().graph_cypher_plan(
            tickers,
            target_ticker=target_ticker,
            topic=topic,
            question=question,
            max_depth=max_depth,
            use_llm=use_llm,
        )

    @router.get("/supply-chain/graph/cypher-query")
    def supply_chain_graph_cypher_query(
        tickers: str = "",
        target_ticker: str = "",
        topic: str = "",
        question: str = "",
        max_depth: int = 3,
        use_llm: bool = False,
        max_records: int = 25,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.supply_chain_graph_api().graph_cypher_query(
            tickers,
            target_ticker=target_ticker,
            topic=topic,
            question=question,
            max_depth=max_depth,
            use_llm=use_llm,
            max_records=max_records,
        )

    @router.post("/supply-chain/graph/neo4j/import")
    def import_supply_chain_graph_neo4j(
        tickers: str = "",
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.supply_chain_graph_api().import_graph_to_neo4j(tickers)

    return router
