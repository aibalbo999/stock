from __future__ import annotations

from collections.abc import Callable

from app.services.supply_chain_graph_cypher import GraphCypherPlannerService
from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.whitelist import SupplyChainWhitelist


class SupplyChainGraphApiService:
    def __init__(
        self,
        *,
        whitelist_cls: type[SupplyChainWhitelist] = SupplyChainWhitelist,
        neo4j_import_service_factory: Callable[[], Neo4jGraphImportService] | None = None,
        cypher_planner_factory: Callable[[], GraphCypherPlannerService] | None = None,
    ) -> None:
        self.whitelist_cls = whitelist_cls
        self.neo4j_import_service_factory = neo4j_import_service_factory or Neo4jGraphImportService
        self.cypher_planner_factory = cypher_planner_factory or GraphCypherPlannerService

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

    def graph_reasoning_payload(
        self,
        tickers: str = "",
        *,
        target_ticker: str = "",
        topic: str = "",
        max_depth: int = 3,
        max_paths: int = 8,
    ) -> dict:
        requested_tickers = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        return self.whitelist_cls().graph().reasoning_plan(
            requested_tickers or None,
            target_ticker=target_ticker,
            topic=topic,
            max_depth=max_depth,
            max_paths=max_paths,
        )

    def graph_cypher_plan(
        self,
        tickers: str = "",
        *,
        target_ticker: str = "",
        topic: str = "",
        question: str = "",
        max_depth: int = 3,
        use_llm: bool = False,
    ) -> dict:
        requested_tickers = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        return self.cypher_planner_factory().plan(
            self.whitelist_cls().graph(),
            tickers=requested_tickers or None,
            target_ticker=target_ticker,
            topic=topic,
            question=question,
            max_depth=max_depth,
            use_llm=use_llm,
        )

    def graph_cypher_query(
        self,
        tickers: str = "",
        *,
        target_ticker: str = "",
        topic: str = "",
        question: str = "",
        max_depth: int = 3,
        use_llm: bool = False,
        max_records: int = 25,
    ) -> dict:
        plan_payload = self.graph_cypher_plan(
            tickers,
            target_ticker=target_ticker,
            topic=topic,
            question=question,
            max_depth=max_depth,
            use_llm=use_llm,
        )
        execution = self.neo4j_import_service_factory().execute_read_query(
            plan_payload["plan"],
            max_records=max_records,
        )
        return {**plan_payload, "execution": execution}

    def import_graph_to_neo4j(self, tickers: str = "") -> dict:
        requested_tickers = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
        graph = self.whitelist_cls().graph()
        return self.neo4j_import_service_factory().import_graph(graph, requested_tickers or None)
