from __future__ import annotations

from collections.abc import Callable

from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.whitelist import SupplyChainWhitelist


class SupplyChainGraphApiService:
    def __init__(
        self,
        *,
        whitelist_cls: type[SupplyChainWhitelist] = SupplyChainWhitelist,
        neo4j_import_service_factory: Callable[[], Neo4jGraphImportService] | None = None,
    ) -> None:
        self.whitelist_cls = whitelist_cls
        self.neo4j_import_service_factory = neo4j_import_service_factory or Neo4jGraphImportService

    def whitelist_payload(self) -> dict:
        return self.whitelist_cls().raw

    def graph_payload(self, tickers: str = "", topic: str = "") -> dict:
        requested_tickers = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        graph = self.whitelist_cls().graph()
        payload = graph.to_dict()
        payload["context"] = graph.render_prompt_context(requested_tickers or None)
        payload["retrieval_hints"] = {
            ticker: [hint.to_dict() for hint in graph.retrieval_hints(ticker)]
            for ticker in requested_tickers
        }
        if hasattr(graph, "retrieval_plan"):
            payload["retrieval_plan"] = graph.retrieval_plan(
                requested_tickers or None,
                topic=topic,
            )
        if not requested_tickers:
            return payload

        requested = set(requested_tickers)
        payload["nodes"] = [
            node
            for node in payload["nodes"]
            if node["ticker"] in requested
            or any(
                edge["source_ticker"] == node["ticker"] or edge["target_ticker"] == node["ticker"]
                for edge in payload["edges"]
                if edge["source_ticker"] in requested or edge["target_ticker"] in requested
            )
        ]
        payload["edges"] = [
            edge
            for edge in payload["edges"]
            if edge["source_ticker"] in requested or edge["target_ticker"] in requested
        ]
        return payload

    def graph_neo4j_payload(self, tickers: str = "") -> dict:
        requested_tickers = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        return self.whitelist_cls().graph().neo4j_import_payload(requested_tickers or None)

    def import_graph_to_neo4j(self, tickers: str = "") -> dict:
        requested_tickers = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        graph = self.whitelist_cls().graph()
        return self.neo4j_import_service_factory().import_graph(graph, requested_tickers or None)
