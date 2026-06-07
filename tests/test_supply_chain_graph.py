from fastapi.testclient import TestClient

from app.api import main
from app.services.supply_chain_graph import SupplyChainGraph
from app.services.whitelist import SupplyChainWhitelist


def test_supply_chain_graph_builds_taxonomy_edges_from_static_whitelist() -> None:
    graph = SupplyChainWhitelist().graph()
    edges = {(edge.source_ticker, edge.target_ticker, edge.relation) for edge in graph.edges}

    assert ("3324", "2382", "structural_upstream_to") in edges
    assert ("3324", "3231", "structural_upstream_to") in edges
    assert ("2382", "3231", "same_segment_peer") in edges
    assert graph.to_dict()["note"].startswith("GraphRAG edges are structural")


def test_supply_chain_graph_context_warns_not_to_treat_graph_as_supplier_proof() -> None:
    graph = SupplyChainWhitelist().graph()
    context = graph.render_prompt_context(["3324"])

    assert "產業鏈關係圖譜" in context
    assert "正式投資理由仍必須回到新聞、公司文件、月營收或財報證據" in context
    assert "3324 雙鴻" in context
    assert "2382 廣達" in context or "3231 緯創" in context


def test_supply_chain_graph_retrieval_hints_preserve_edge_direction() -> None:
    graph = SupplyChainWhitelist().graph()

    server_hints = graph.retrieval_hints("2382")
    thermal_hints = graph.retrieval_hints("3324")

    upstream_hint = next(hint for hint in server_hints if hint.ticker == "3324")
    downstream_hint = next(hint for hint in thermal_hints if hint.ticker == "2382")

    assert upstream_hint.direction == "upstream"
    assert upstream_hint.relation_label == "上游供應鏈"
    assert upstream_hint.confidence == "taxonomy"
    assert "3324" in upstream_hint.search_terms()
    assert downstream_hint.direction == "downstream"
    assert downstream_hint.relation_label == "下游需求端"


def test_supply_chain_graph_retrieval_plan_builds_evidence_bound_queries() -> None:
    graph = SupplyChainWhitelist().graph()

    plan = graph.retrieval_plan(["3324"], topic="AI 伺服器散熱")
    queries = plan["queries_by_ticker"]["3324"]

    assert plan["strategy"] == "taxonomy_graph_query_expansion"
    assert "not accepted as investment evidence unless corroborated" in plan["evidence_policy"]
    assert queries[0]["query_type"] == "company_graph_neighborhood"
    assert queries[0]["evidence_policy"] == "graph_hint_requires_source_confirmation"
    assert "3324" in queries[0]["query"]
    assert "雙鴻" in queries[0]["query"]
    assert any(query["query_type"] == "relation_confirmation" for query in queries)
    relation_query = next(query for query in queries if query["query_type"] == "relation_confirmation")
    assert relation_query["related_tickers"]
    assert relation_query["relation_scope"] in {"downstream", "peer", "upstream"}


def test_supply_chain_graph_reasoning_plan_builds_shortest_path_context() -> None:
    graph = SupplyChainWhitelist().graph()

    plan = graph.reasoning_plan(
        ["3324"],
        target_ticker="2382",
        topic="AI 伺服器散熱",
        max_depth=3,
    )
    paths = plan["paths_by_ticker"]["3324"]

    assert plan["strategy"] == "taxonomy_graph_shortest_path_reasoning"
    assert "Shortest paths are graph-derived structural hypotheses" in plan["evidence_policy"]
    assert "GraphRAG 路徑推理" in plan["context"]
    assert paths
    assert paths[0]["path_tickers"] == ["3324", "2382"]
    assert paths[0]["hop_count"] == 1
    assert paths[0]["impact_direction"] == "downstream_demand_path"
    assert paths[0]["edges"][0]["direction_from_previous"] == "downstream"
    assert paths[0]["evidence_policy"] == "graph_path_requires_source_confirmation"
    assert "shortestPath" in plan["cypher_templates"]["shortest_path_between_companies"]


def test_dynamic_whitelist_graph_connects_robot_components_to_robot_systems() -> None:
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "伺服驅動與控制系統",
                "status": "evidence_supported",
                "evidence_keywords": ["伺服驅動", "控制器"],
            },
            {
                "ticker": "6188",
                "name": "廣明",
                "segment": "協作型機器人",
                "status": "evidence_supported",
                "evidence_keywords": ["協作型機器人"],
            },
            {
                "ticker": "9999",
                "name": "測試公司",
                "segment": "協作型機器人",
                "status": "needs_evidence",
                "evidence_keywords": ["協作型機器人"],
            },
        ]
    )
    graph = whitelist.graph()

    assert [node.ticker for node in graph.nodes] == ["2308", "6188"]
    assert any(
        edge.source_ticker == "2308"
        and edge.target_ticker == "6188"
        and edge.relation == "structural_upstream_to"
        for edge in graph.edges
    )
    assert "2308 台達電" in whitelist.as_prompt_context()
    assert "產業鏈關係圖譜" in whitelist.as_prompt_context()


def test_supply_chain_graph_classifier_handles_known_segments() -> None:
    whitelist = SupplyChainWhitelist()
    categories = {
        segment.name: SupplyChainGraph.classify_segment(segment)
        for segment in whitelist.segments
    }

    assert categories["晶圓代工"] == "foundry"
    assert categories["AI 伺服器代工"] == "server_odm"
    assert categories["散熱"] == "power_thermal"


def test_supply_chain_graph_endpoint_can_focus_on_requested_ticker() -> None:
    response = TestClient(main.app).get("/supply-chain/graph?tickers=3324&topic=AI%20伺服器散熱")

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"]
    assert all(
        edge["source_ticker"] == "3324" or edge["target_ticker"] == "3324"
        for edge in body["edges"]
    )
    assert "GraphRAG" in body["context"]
    assert body["retrieval_plan"]["queries_by_ticker"]["3324"]
    assert body["retrieval_plan"]["queries_by_ticker"]["3324"][0]["query_type"] == "company_graph_neighborhood"


def test_supply_chain_graph_neo4j_export_uses_parameterized_cypher() -> None:
    graph = SupplyChainWhitelist().graph()
    payload = graph.neo4j_import_payload(["3324"])

    assert payload["format"] == "neo4j_cypher_v1"
    assert payload["parameters"]["nodes"]
    assert any(node["ticker"] == "3324" for node in payload["parameters"]["nodes"])
    assert any(
        edge["source_ticker"] == "3324" or edge["target_ticker"] == "3324"
        for edge in payload["parameters"]["structural_edges"]
    )
    assert any("$nodes" in statement for statement in payload["statements"])
    assert any("$structural_edges" in statement for statement in payload["statements"])
    assert "STRUCTURAL_UPSTREAM_TO" in payload["query_examples"]["upstream_suppliers"]
    assert "not proof of a direct supplier contract" in payload["note"]


def test_supply_chain_graph_neo4j_endpoint_can_focus_on_requested_ticker() -> None:
    response = TestClient(main.app).get("/supply-chain/graph/neo4j?tickers=3324")

    assert response.status_code == 200
    body = response.json()
    node_tickers = {node["ticker"] for node in body["parameters"]["nodes"]}
    assert "3324" in node_tickers
    assert all(
        edge["source_ticker"] in node_tickers and edge["target_ticker"] in node_tickers
        for edge in [*body["parameters"]["structural_edges"], *body["parameters"]["peer_edges"]]
    )
    assert body["query_examples"]["downstream_demand"].startswith("MATCH")
    assert "shortestPath" in body["query_examples"]["shortest_path_between_companies"]


def test_supply_chain_graph_reasoning_endpoint_returns_shortest_paths() -> None:
    response = TestClient(main.app).get(
        "/supply-chain/graph/reasoning?tickers=3324&target_ticker=2382&topic=AI%20伺服器散熱"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target_ticker"] == "2382"
    assert body["paths_by_ticker"]["3324"][0]["path_tickers"] == ["3324", "2382"]
    assert body["paths_by_ticker"]["3324"][0]["impact_direction_label"] == "往下游追蹤需求/出貨傳導"
    assert "GraphRAG 路徑推理" in body["context"]


def test_supply_chain_graph_cypher_plan_endpoint_returns_guarded_plan() -> None:
    response = TestClient(main.app).get(
        "/supply-chain/graph/cypher-plan"
        "?tickers=3324&target_ticker=2382&topic=AI%20伺服器散熱&question=上下游衝擊"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "guarded_llm_cypher_planner"
    assert body["plan"]["validation"]["valid"] is True
    assert body["plan"]["validation"]["read_only"] is True
    assert "MATCH" in body["plan"]["cypher"]


def test_supply_chain_graph_cypher_query_endpoint_degrades_without_neo4j() -> None:
    response = TestClient(main.app).get(
        "/supply-chain/graph/cypher-query"
        "?tickers=3324&target_ticker=2382&topic=AI%20伺服器散熱&question=上下游衝擊"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "guarded_llm_cypher_planner"
    assert body["plan"]["validation"]["valid"] is True
    assert body["execution"]["status"] == "not_configured"
    assert body["execution"]["validation"]["valid"] is True
    assert body["execution"]["neo4j"]["fallback_reason"] == "missing_settings:neo4j_uri"


def test_supply_chain_graph_neo4j_import_endpoint_is_safe_without_config() -> None:
    response = TestClient(main.app).post("/supply-chain/graph/neo4j/import?tickers=3324")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_configured"
    assert body["neo4j"]["fallback_reason"] == "missing_settings:neo4j_uri"
    assert body["payload"]["format"] == "neo4j_cypher_v1"
