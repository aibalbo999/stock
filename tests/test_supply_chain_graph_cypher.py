from __future__ import annotations

from app.services.llm_client import LLMResult
from app.services.supply_chain_graph_cypher import (
    GraphCypherPlannerService,
    parse_llm_cypher_json,
    validate_graph_cypher_plan,
)
from app.services.whitelist import SupplyChainWhitelist


def test_guarded_cypher_planner_builds_valid_shortest_path_template() -> None:
    graph = SupplyChainWhitelist().graph()
    plan = GraphCypherPlannerService().plan(
        graph,
        tickers=["3324"],
        target_ticker="2382",
        topic="AI 伺服器散熱",
        question="雙鴻對廣達的上下游衝擊",
    )

    assert plan["strategy"] == "guarded_llm_cypher_planner"
    assert plan["planner"] == "deterministic_guarded"
    assert plan["plan"]["intent"] == "shortest_path_between_companies"
    assert plan["plan"]["validation"]["valid"] is True
    assert plan["plan"]["validation"]["read_only"] is True
    assert "shortestPath" in plan["plan"]["cypher"]
    assert plan["allowed_schema"]["relationship_types"] == [
        "SAME_SEGMENT_PEER",
        "STRUCTURAL_UPSTREAM_TO",
    ]
    assert "CALL/CREATE/MERGE" in plan["prompt"]


def test_guarded_cypher_planner_accepts_valid_llm_plan() -> None:
    graph = SupplyChainWhitelist().graph()

    class FakeLLM:
        def generate_with_metadata(self, prompt: str) -> LLMResult:
            assert "只輸出 JSON" in prompt
            return LLMResult(
                text=(
                    '{"intent":"downstream_demand_path",'
                    '"cypher":"MATCH (source:Company {ticker: $ticker})-'
                    '[:STRUCTURAL_UPSTREAM_TO*1..2]->(customer:Company) '
                    'RETURN source, customer LIMIT $limit",'
                    '"parameters":{"ticker":"3324","limit":8},'
                    '"rationale":"validated downstream demand path"}'
                ),
                provider="fake",
                model="fake-vision",
                observability={"latency_ms": 1.2},
            )

    payload = GraphCypherPlannerService(llm_client_factory=lambda: FakeLLM()).plan(
        graph,
        tickers=["3324"],
        question="下游需求傳導",
        use_llm=True,
    )

    assert payload["planner"] == "llm_guarded"
    assert payload["llm"]["attempted"] is True
    assert payload["llm"]["used"] is True
    assert payload["plan"]["source"] == "llm_validated"
    assert payload["plan"]["validation"]["valid"] is True


def test_guarded_cypher_planner_rejects_write_or_unknown_schema_llm_plan() -> None:
    graph = SupplyChainWhitelist().graph()

    class FakeLLM:
        def generate_with_metadata(self, _prompt: str) -> LLMResult:
            return LLMResult(
                text=(
                    '{"intent":"bad",'
                    '"cypher":"MATCH (c:Company) DELETE c RETURN c",'
                    '"parameters":{},'
                    '"rationale":"bad"}'
                ),
                provider="fake",
                model="fake",
            )

    payload = GraphCypherPlannerService(llm_client_factory=lambda: FakeLLM()).plan(
        graph,
        tickers=["3324"],
        question="任意修改圖譜",
        use_llm=True,
    )

    assert payload["planner"] == "deterministic_guarded"
    assert payload["llm"]["attempted"] is True
    assert payload["llm"]["used"] is False
    assert payload["llm"]["fallback_reason"] == "llm_cypher_validation_failed"
    assert any(error.startswith("blocked_keywords") for error in payload["llm"]["validation_errors"])
    assert payload["plan"]["validation"]["valid"] is True


def test_cypher_validator_rejects_unknown_ticker_and_depth() -> None:
    graph = SupplyChainWhitelist().graph()

    validation = validate_graph_cypher_plan(
        {
            "cypher": (
                "MATCH path = shortestPath((a:Company {ticker: $source_ticker})-[*..9]-"
                "(b:Company {ticker: $target_ticker})) RETURN path"
            ),
            "parameters": {"source_ticker": "9999", "target_ticker": "2382"},
        },
        graph,
        max_depth=3,
    )

    assert validation["valid"] is False
    assert "path_depth_exceeds_limit" in validation["errors"]
    assert "unknown_ticker_parameters:9999" in validation["errors"]


def test_cypher_validator_requires_small_parameterized_clause_subset() -> None:
    graph = SupplyChainWhitelist().graph()

    validation = validate_graph_cypher_plan(
        {
            "cypher": (
                "MATCH (c:Company) WITH c "
                "MATCH (p:Company) RETURN c, p UNION MATCH (x:Company) RETURN x"
            ),
            "parameters": {},
        },
        graph,
        max_depth=3,
    )

    assert validation["valid"] is False
    assert "cypher_must_be_parameterized" in validation["errors"]
    assert "disallowed_clauses:UNION,WITH" in validation["errors"]


def test_parse_llm_cypher_json_accepts_fenced_json() -> None:
    payload = parse_llm_cypher_json('```json\n{"intent":"x","cypher":"MATCH (c) RETURN c"}\n```')

    assert payload["intent"] == "x"
