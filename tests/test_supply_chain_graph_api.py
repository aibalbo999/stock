from __future__ import annotations

from app.services.supply_chain_graph_api import SupplyChainGraphApiService


def test_supply_chain_graph_api_filters_graph_to_requested_ticker_neighborhood() -> None:
    class FakeGraph:
        def to_dict(self):
            return {
                "nodes": [
                    {"ticker": "2330", "name": "台積電"},
                    {"ticker": "3711", "name": "日月光投控"},
                    {"ticker": "9999", "name": "無關公司"},
                ],
                "edges": [
                    {"source_ticker": "2330", "target_ticker": "3711"},
                    {"source_ticker": "9999", "target_ticker": "8888"},
                ],
                "note": "taxonomy",
            }

        def render_prompt_context(self, tickers):
            return "context:" + ",".join(tickers or [])

        def retrieval_hints(self, ticker):
            return [
                type(
                    "Hint",
                    (),
                    {"to_dict": lambda self: {"ticker": "3711", "direction": "downstream"}},
                )()
            ]

        def retrieval_plan(self, tickers, topic=""):
            return {
                "tickers": tickers,
                "topic": topic,
                "queries_by_ticker": {"2330": [{"query": f"{topic} 2330 3711"}]},
            }

    class FakeWhitelist:
        raw = {"segments": []}

        def graph(self):
            return FakeGraph()

    service = SupplyChainGraphApiService(whitelist_cls=FakeWhitelist)

    assert service.whitelist_payload() == {"segments": []}
    payload = service.graph_payload("2330", topic="AI 供應鏈")

    assert payload["context"] == "context:2330"
    assert payload["retrieval_hints"] == {"2330": [{"ticker": "3711", "direction": "downstream"}]}
    assert payload["retrieval_plan"]["topic"] == "AI 供應鏈"
    assert payload["retrieval_plan"]["queries_by_ticker"]["2330"][0]["query"] == "AI 供應鏈 2330 3711"
    assert {node["ticker"] for node in payload["nodes"]} == {"2330", "3711"}
    assert payload["edges"] == [{"source_ticker": "2330", "target_ticker": "3711"}]


def test_supply_chain_graph_api_returns_full_graph_without_requested_tickers() -> None:
    class FakeGraph:
        def to_dict(self):
            return {
                "nodes": [{"ticker": "2330"}, {"ticker": "9999"}],
                "edges": [{"source_ticker": "2330", "target_ticker": "9999"}],
            }

        def render_prompt_context(self, tickers):
            return "all" if tickers is None else "filtered"

        def retrieval_hints(self, ticker):
            raise AssertionError("full graph payload should not request ticker-specific hints")

    class FakeWhitelist:
        raw = {}

        def graph(self):
            return FakeGraph()

    payload = SupplyChainGraphApiService(whitelist_cls=FakeWhitelist).graph_payload("")

    assert payload["context"] == "all"
    assert {node["ticker"] for node in payload["nodes"]} == {"2330", "9999"}


def test_supply_chain_graph_api_delegates_neo4j_import_with_requested_tickers() -> None:
    captured = {}

    class FakeGraph:
        pass

    class FakeWhitelist:
        def graph(self):
            return FakeGraph()

    class FakeImportService:
        def import_graph(self, graph, tickers):
            captured["graph"] = graph
            captured["tickers"] = tickers
            return {"status": "imported"}

    service = SupplyChainGraphApiService(
        whitelist_cls=FakeWhitelist,
        neo4j_import_service_factory=lambda: FakeImportService(),
    )

    result = service.import_graph_to_neo4j("2330, 3324")

    assert result == {"status": "imported"}
    assert isinstance(captured["graph"], FakeGraph)
    assert captured["tickers"] == ["2330", "3324"]


def test_supply_chain_graph_api_delegates_reasoning_payload() -> None:
    captured = {}

    class FakeGraph:
        def reasoning_plan(self, tickers, *, target_ticker="", topic="", max_depth=3, max_paths=8):
            captured["tickers"] = tickers
            captured["target_ticker"] = target_ticker
            captured["topic"] = topic
            captured["max_depth"] = max_depth
            captured["max_paths"] = max_paths
            return {"strategy": "taxonomy_graph_shortest_path_reasoning"}

    class FakeWhitelist:
        def graph(self):
            return FakeGraph()

    service = SupplyChainGraphApiService(whitelist_cls=FakeWhitelist)

    result = service.graph_reasoning_payload(
        "2330, 3324",
        target_ticker="2382",
        topic="AI 伺服器",
        max_depth=4,
        max_paths=6,
    )

    assert result == {"strategy": "taxonomy_graph_shortest_path_reasoning"}
    assert captured == {
        "tickers": ["2330", "3324"],
        "target_ticker": "2382",
        "topic": "AI 伺服器",
        "max_depth": 4,
        "max_paths": 6,
    }


def test_supply_chain_graph_api_delegates_cypher_plan() -> None:
    captured = {}

    class FakeGraph:
        pass

    class FakeWhitelist:
        def graph(self):
            return FakeGraph()

    class FakePlanner:
        def plan(self, graph, *, tickers=None, target_ticker="", topic="", question="", max_depth=3, use_llm=False):
            captured["graph"] = graph
            captured["tickers"] = tickers
            captured["target_ticker"] = target_ticker
            captured["topic"] = topic
            captured["question"] = question
            captured["max_depth"] = max_depth
            captured["use_llm"] = use_llm
            return {"strategy": "guarded_llm_cypher_planner"}

    service = SupplyChainGraphApiService(
        whitelist_cls=FakeWhitelist,
        cypher_planner_factory=lambda: FakePlanner(),
    )

    result = service.graph_cypher_plan(
        "2330, 3324",
        target_ticker="2382",
        topic="AI 伺服器",
        question="上下游衝擊",
        max_depth=4,
        use_llm=True,
    )

    assert result == {"strategy": "guarded_llm_cypher_planner"}
    assert isinstance(captured["graph"], FakeGraph)
    assert captured == {
        "graph": captured["graph"],
        "tickers": ["2330", "3324"],
        "target_ticker": "2382",
        "topic": "AI 伺服器",
        "question": "上下游衝擊",
        "max_depth": 4,
        "use_llm": True,
    }


def test_supply_chain_graph_api_delegates_live_cypher_query() -> None:
    captured = {}

    class FakeGraph:
        pass

    class FakeWhitelist:
        def graph(self):
            return FakeGraph()

    class FakePlanner:
        def plan(self, graph, *, tickers=None, target_ticker="", topic="", question="", max_depth=3, use_llm=False):
            captured["planner"] = {
                "graph": graph,
                "tickers": tickers,
                "target_ticker": target_ticker,
                "topic": topic,
                "question": question,
                "max_depth": max_depth,
                "use_llm": use_llm,
            }
            return {
                "strategy": "guarded_llm_cypher_planner",
                "plan": {"cypher": "MATCH (c:Company) RETURN c LIMIT $limit"},
            }

    class FakeImportService:
        def execute_read_query(self, plan, *, max_records=25):
            captured["execution"] = {"plan": plan, "max_records": max_records}
            return {"status": "executed"}

    service = SupplyChainGraphApiService(
        whitelist_cls=FakeWhitelist,
        cypher_planner_factory=lambda: FakePlanner(),
        neo4j_import_service_factory=lambda: FakeImportService(),
    )

    result = service.graph_cypher_query(
        "2330, 3324",
        target_ticker="2382",
        topic="AI 伺服器",
        question="上下游衝擊",
        max_depth=4,
        use_llm=True,
        max_records=7,
    )

    assert result["strategy"] == "guarded_llm_cypher_planner"
    assert result["execution"] == {"status": "executed"}
    assert captured["planner"]["tickers"] == ["2330", "3324"]
    assert captured["planner"]["max_depth"] == 4
    assert captured["planner"]["use_llm"] is True
    assert captured["execution"]["max_records"] == 7
    assert captured["execution"]["plan"] == {"cypher": "MATCH (c:Company) RETURN c LIMIT $limit"}
