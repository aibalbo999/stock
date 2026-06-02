from scripts.import_supply_chain_graph_neo4j import run


class FakeGraphService:
    def __init__(self) -> None:
        self.calls = []

    def graph_neo4j_payload(self, tickers: str) -> dict:
        self.calls.append(("payload", tickers))
        return {
            "format": "neo4j_cypher_v1",
            "parameters": {"nodes": [{"ticker": "2330"}]},
            "statements": ["RETURN 1"],
        }

    def import_graph_to_neo4j(self, tickers: str) -> dict:
        self.calls.append(("import", tickers))
        return {"status": "imported", "node_count": 1}


def test_graph_neo4j_script_dry_run_outputs_payload(capsys, tmp_path) -> None:
    service = FakeGraphService()
    output = tmp_path / "graph.json"

    exit_code = run(["--dry-run", "--tickers", "2330", "--output", str(output)], service=service)

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert service.calls == [("payload", "2330")]
    assert '"status": "dry_run"' in captured
    assert '"format": "neo4j_cypher_v1"' in output.read_text(encoding="utf-8")


def test_graph_neo4j_script_import_returns_nonzero_when_not_configured(capsys) -> None:
    class NotConfiguredService(FakeGraphService):
        def import_graph_to_neo4j(self, tickers: str) -> dict:
            self.calls.append(("import", tickers))
            return {"status": "not_configured", "neo4j": {"fallback_reason": "missing_settings:neo4j_uri"}}

    service = NotConfiguredService()

    exit_code = run(["--tickers", "2330"], service=service)

    captured = capsys.readouterr().out
    assert exit_code == 2
    assert service.calls == [("import", "2330")]
    assert "missing_settings:neo4j_uri" in captured


def test_graph_neo4j_script_import_success(capsys) -> None:
    service = FakeGraphService()

    exit_code = run(["--tickers", "2330"], service=service)

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert service.calls == [("import", "2330")]
    assert '"status": "imported"' in captured
