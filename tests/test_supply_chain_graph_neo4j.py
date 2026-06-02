from types import SimpleNamespace

from app.services.supply_chain_graph_neo4j import Neo4jGraphImportService
from app.services.whitelist import SupplyChainWhitelist


def test_neo4j_graph_import_status_reports_missing_uri() -> None:
    service = Neo4jGraphImportService(
        settings_provider=lambda: SimpleNamespace(
            neo4j_uri="",
            neo4j_database="",
            neo4j_user="",
            neo4j_password=None,
            neo4j_timeout_seconds=15.0,
            neo4j_status_check_connection=True,
        ),
        dependency_checker=lambda dependency: True,
    )

    status = service.status()

    assert status["ready"] is False
    assert status["configured"] is False
    assert status["dependency_available"] is True
    assert status["connection_checked"] is False
    assert status["connection_ok"] is None
    assert status["fallback_reason"] == "missing_settings:neo4j_uri"
    assert status["local_docker_defaults"]["compose_service"] == "neo4j"
    assert status["local_docker_defaults"]["default_uri"] == "neo4j://localhost:7687"
    assert "NEO4J_PASSWORD" in status["local_docker_defaults"]["env_keys"]
    assert "stock_ai_neo4j_password" not in str(status["local_docker_defaults"])


def test_neo4j_graph_import_status_probes_connection_when_configured() -> None:
    captured = {}

    class FakeResult:
        def consume(self):
            captured["consumed"] = True

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            captured["session_closed"] = True

        def run(self, statement):
            captured["probe_statement"] = statement
            return FakeResult()

    class FakeDriver:
        def session(self, database=None):
            captured["database"] = database
            return FakeSession()

        def close(self):
            captured["driver_closed"] = True

    service = Neo4jGraphImportService(
        settings_provider=lambda: SimpleNamespace(
            neo4j_uri="neo4j://localhost:7687",
            neo4j_database="neo4j",
            neo4j_user="neo4j",
            neo4j_password="secret",
            neo4j_timeout_seconds=15.0,
            neo4j_status_check_connection=True,
        ),
        driver_factory=lambda uri, auth=None: FakeDriver(),
    )

    status = service.status()

    assert status["ready"] is True
    assert status["connection_checked"] is True
    assert status["connection_ok"] is True
    assert status["connection_error"] is None
    assert status["fallback_reason"] is None
    assert captured["database"] == "neo4j"
    assert captured["probe_statement"] == "RETURN 1 AS ok"
    assert captured["consumed"] is True
    assert captured["session_closed"] is True
    assert captured["driver_closed"] is True


def test_neo4j_graph_import_status_reports_connection_failure() -> None:
    captured = {}

    class FailingDriver:
        def session(self, database=None):
            raise RuntimeError("connection refused")

        def close(self):
            captured["driver_closed"] = True

    service = Neo4jGraphImportService(
        settings_provider=lambda: SimpleNamespace(
            neo4j_uri="neo4j://localhost:7687",
            neo4j_database="neo4j",
            neo4j_user="neo4j",
            neo4j_password="secret",
            neo4j_timeout_seconds=15.0,
            neo4j_status_check_connection=True,
        ),
        driver_factory=lambda uri, auth=None: FailingDriver(),
    )

    status = service.status()

    assert status["ready"] is False
    assert status["configured"] is True
    assert status["dependency_available"] is True
    assert status["connection_checked"] is True
    assert status["connection_ok"] is False
    assert status["connection_error"] == "connection refused"
    assert status["fallback_reason"] == "connection_failed:neo4j"
    assert captured["driver_closed"] is True


def test_neo4j_graph_import_returns_payload_when_not_configured() -> None:
    service = Neo4jGraphImportService(
        settings_provider=lambda: SimpleNamespace(
            neo4j_uri="",
            neo4j_database="",
            neo4j_user="",
            neo4j_password=None,
            neo4j_timeout_seconds=15.0,
            neo4j_status_check_connection=True,
        ),
        dependency_checker=lambda dependency: True,
    )

    result = service.import_graph(SupplyChainWhitelist().graph(), ["3324"])

    assert result["status"] == "not_configured"
    assert result["neo4j"]["fallback_reason"] == "missing_settings:neo4j_uri"
    assert result["payload"]["format"] == "neo4j_cypher_v1"


def test_neo4j_graph_import_runs_parameterized_statements_and_closes_driver() -> None:
    captured = {"runs": []}

    class FakeResult:
        def consume(self):
            captured.setdefault("consumed", 0)
            captured["consumed"] += 1

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            captured["session_closed"] = True

        def run(self, statement, parameters):
            captured["runs"].append((statement, parameters))
            return FakeResult()

    class FakeDriver:
        def session(self, database=None):
            captured["database"] = database
            return FakeSession()

        def close(self):
            captured["driver_closed"] = True

    def driver_factory(uri, auth=None):
        captured["driver"] = {"uri": uri, "auth": auth}
        return FakeDriver()

    service = Neo4jGraphImportService(
        settings_provider=lambda: SimpleNamespace(
            neo4j_uri="neo4j://localhost:7687",
            neo4j_database="stock",
            neo4j_user="neo4j",
            neo4j_password="secret",
            neo4j_timeout_seconds=15.0,
            neo4j_status_check_connection=True,
        ),
        driver_factory=driver_factory,
    )

    result = service.import_graph(SupplyChainWhitelist().graph(), ["3324"])

    assert captured["driver"] == {
        "uri": "neo4j://localhost:7687",
        "auth": ("neo4j", "secret"),
    }
    assert captured["database"] == "stock"
    assert len(captured["runs"]) == result["statement_count"]
    assert all("nodes" in parameters for _statement, parameters in captured["runs"])
    assert any("$structural_edges" in statement for statement, _parameters in captured["runs"])
    assert captured["consumed"] == result["statement_count"]
    assert captured["session_closed"] is True
    assert captured["driver_closed"] is True
    assert result["status"] == "imported"
    assert result["node_count"] >= 1
    assert result["structural_edge_count"] >= 1


def test_neo4j_graph_import_returns_actionable_failure_when_connection_fails() -> None:
    captured = {}

    class FailingDriver:
        def session(self, database=None):
            raise RuntimeError("connection refused")

        def close(self):
            captured["driver_closed"] = True

    service = Neo4jGraphImportService(
        settings_provider=lambda: SimpleNamespace(
            neo4j_uri="neo4j://localhost:7687",
            neo4j_database="neo4j",
            neo4j_user="neo4j",
            neo4j_password="secret",
            neo4j_timeout_seconds=15.0,
            neo4j_status_check_connection=True,
        ),
        driver_factory=lambda uri, auth=None: FailingDriver(),
    )

    result = service.import_graph(SupplyChainWhitelist().graph(), ["3324"])

    assert result["status"] == "import_failed"
    assert result["neo4j"]["fallback_reason"] == "neo4j_import_failed"
    assert result["error"] == "connection refused"
    assert result["retryable"] is True
    assert result["payload"]["format"] == "neo4j_cypher_v1"
    assert captured["driver_closed"] is True
