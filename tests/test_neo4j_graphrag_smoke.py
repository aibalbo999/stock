from __future__ import annotations

import os

from app.core.config import get_settings
from scripts import neo4j_graphrag_smoke as smoke


def _payload(*, ready: bool = True) -> dict:
    return {
        "format": "neo4j_cypher_v1" if ready else "bad",
        "statements": ["RETURN 1"] if ready else [],
        "parameters": {
            "nodes": [{"ticker": "2330"}] if ready else [],
            "structural_edges": [{"source_ticker": "2330", "target_ticker": "2382"}],
            "peer_edges": [],
        },
    }


def _query(status: str = "executed", *, row_count: int = 0) -> dict:
    return {
        "strategy": "guarded_llm_cypher_planner",
        "planner": "deterministic_guarded",
        "plan": {
            "intent": "shortest_path_between_companies",
            "source": "deterministic_template",
            "cypher": (
                "MATCH path = shortestPath("
                "(source:Company {ticker: $source_ticker})-[*..3]-"
                "(target:Company {ticker: $target_ticker})"
                ") RETURN path LIMIT $limit"
            ),
            "parameters": {
                "source_ticker": "2330",
                "target_ticker": "2382",
                "limit": 8,
            },
            "validation": {"valid": True, "errors": [], "read_only": True},
        },
        "execution": {
            "status": status,
            "row_count": row_count,
            "record_limit": 8,
            "validation": {"valid": True, "errors": [], "read_only": True},
            "neo4j": {"fallback_reason": None if status == "executed" else "missing_settings:neo4j_uri"},
        },
        "local_dry_run": {
            "status": "executed_dry_run",
            "ready": True,
            "execution_mode": "in_memory_graph",
            "row_count": 1,
            "validation": {"valid": True, "errors": [], "read_only": True},
            "evidence_policy": "production live reads still require Neo4j",
        },
    }


class FakeGraphService:
    def __init__(self, *, payload_ready: bool = True, query_status: str = "executed") -> None:
        self.calls = []
        self.payload_ready = payload_ready
        self.query_status = query_status

    def graph_neo4j_payload(self, tickers: str) -> dict:
        self.calls.append(("payload", tickers))
        return _payload(ready=self.payload_ready)

    def graph_cypher_query(self, tickers: str, **kwargs) -> dict:
        self.calls.append(("query", tickers, kwargs))
        return _query(self.query_status)

    def graph_cypher_plan(self, tickers: str, **kwargs) -> dict:
        self.calls.append(("plan", tickers, kwargs))
        query = _query(self.query_status)
        return {
            "strategy": query["strategy"],
            "planner": query["planner"],
            "plan": query["plan"],
            "local_dry_run": query["local_dry_run"],
        }

    def import_graph_to_neo4j(self, tickers: str) -> dict:
        self.calls.append(("import", tickers))
        return {"status": "imported", "node_count": 1}


def test_neo4j_graphrag_smoke_reports_ready() -> None:
    service = FakeGraphService()

    report = smoke.neo4j_graphrag_smoke_report(
        tickers="2330",
        target_ticker="2382",
        question="上下游衝擊",
        service=service,
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["payload"]["ready"] is True
    assert report["query_result"]["execution"]["status"] == "executed"
    assert report["query_result"]["local_dry_run"]["status"] == "executed_dry_run"
    assert report["query_result"]["local_dry_run"]["row_count"] == 1
    assert service.calls[0] == ("payload", "2330")
    assert service.calls[1][0] == "query"
    assert service.calls[1][2]["target_ticker"] == "2382"
    assert smoke.smoke_exit_code(report, strict=True) == 0


def test_neo4j_graphrag_smoke_treats_missing_neo4j_as_optional_by_default() -> None:
    report = smoke.neo4j_graphrag_smoke_report(
        service=FakeGraphService(query_status="not_configured")
    )

    assert report["status"] == "not_configured"
    assert report["ready"] is False
    assert report["query_result"]["local_dry_run"]["ready"] is True
    assert "NEO4J_URI" in report["remediation"]
    assert smoke.smoke_exit_code(report, strict=False) == 0
    assert smoke.smoke_exit_code(report, strict=True) == 1


def test_neo4j_graphrag_smoke_reports_payload_degraded_before_query_status() -> None:
    report = smoke.neo4j_graphrag_smoke_report(
        service=FakeGraphService(payload_ready=False, query_status="executed")
    )

    assert report["status"] == "payload_degraded"
    assert report["ready"] is False
    assert report["payload"]["ready"] is False
    assert "/supply-chain/graph/neo4j" in report["remediation"]
    assert smoke.smoke_exit_code(report, strict=False) == 1


def test_neo4j_graphrag_smoke_can_import_first() -> None:
    service = FakeGraphService()

    report = smoke.neo4j_graphrag_smoke_report(import_first=True, service=service)

    assert report["status"] == "ready"
    assert report["import_first"] is True
    assert report["import_result"]["status"] == "imported"
    assert [call[0] for call in service.calls] == ["payload", "import", "query"]


def test_neo4j_graphrag_local_contract_does_not_require_live_neo4j() -> None:
    service = FakeGraphService(query_status="not_configured")

    report = smoke.neo4j_graphrag_local_contract_report(
        tickers="2330",
        target_ticker="2382",
        question="上下游衝擊",
        service=service,
    )

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["local_contract"] is True
    assert report["payload"]["ready"] is True
    assert "execution" not in report["query_result"]
    assert report["query_result"]["plan"]["validation"]["read_only"] is True
    assert report["query_result"]["local_dry_run"]["status"] == "executed_dry_run"
    assert "--local-contract" in report["local_contract_command"]
    assert [call[0] for call in service.calls] == ["payload", "plan"]
    assert smoke.smoke_exit_code(report, strict=True) == 0


def test_neo4j_graphrag_smoke_stops_when_import_first_fails() -> None:
    class ImportFailingService(FakeGraphService):
        def import_graph_to_neo4j(self, tickers: str) -> dict:
            self.calls.append(("import", tickers))
            return {"status": "import_failed", "error": "auth failed"}

    service = ImportFailingService()

    report = smoke.neo4j_graphrag_smoke_report(import_first=True, service=service)

    assert report["status"] == "failed"
    assert report["ready"] is False
    assert report["query_result"] is None
    assert [call[0] for call in service.calls] == ["payload", "import"]


def test_neo4j_graphrag_smoke_main_prints_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "neo4j_graphrag_smoke_report",
        lambda **_kwargs: {"status": "ready", "ready": True},
    )

    assert smoke.main(["--json"]) == 0
    assert '"status": "ready"' in capsys.readouterr().out


def test_neo4j_graphrag_smoke_main_can_apply_local_defaults(monkeypatch, capsys) -> None:
    neo4j_env_keys = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")
    for key in neo4j_env_keys:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    assert get_settings().neo4j_uri == ""
    captured = {}

    def fake_report(**_kwargs) -> dict:
        captured["neo4j_uri"] = os.environ.get("NEO4J_URI")
        captured["neo4j_user"] = os.environ.get("NEO4J_USER")
        captured["settings_neo4j_uri"] = get_settings().neo4j_uri
        return {"status": "ready", "ready": True}

    monkeypatch.setattr(smoke, "neo4j_graphrag_smoke_report", fake_report)

    try:
        assert smoke.main(["--local-neo4j-defaults", "--json"]) == 0

        output = capsys.readouterr().out
        assert captured["neo4j_uri"] == "neo4j://localhost:7687"
        assert captured["neo4j_user"] == "neo4j"
        assert captured["settings_neo4j_uri"] == "neo4j://localhost:7687"
        assert '"local_neo4j_defaults"' in output
        assert "NEO4J_PASSWORD" in output
    finally:
        for key in neo4j_env_keys:
            os.environ.pop(key, None)
        get_settings.cache_clear()
