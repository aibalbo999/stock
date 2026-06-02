from __future__ import annotations

from collections.abc import Callable
from importlib.util import find_spec
from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings


LOCAL_NEO4J_ENV_DEFAULTS = {
    "NEO4J_URI": "neo4j://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "stock_ai_neo4j_password",
    "NEO4J_DATABASE": "neo4j",
}


class Neo4jGraphImportService:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any] = get_settings,
        driver_factory: Callable | None = None,
        dependency_checker: Callable[[str], bool] | None = None,
    ) -> None:
        self.settings_provider = settings_provider
        self.driver_factory = driver_factory
        self.dependency_checker = dependency_checker or _module_available

    def status(self, verify_connection: bool | None = None) -> dict:
        settings = self.settings_provider()
        uri = str(getattr(settings, "neo4j_uri", "") or "").strip()
        database = str(getattr(settings, "neo4j_database", "") or "").strip()
        dependency_available = bool(self.driver_factory) or self._dependency_available()
        configured = bool(uri)
        should_verify_connection = (
            bool(getattr(settings, "neo4j_status_check_connection", True))
            if verify_connection is None
            else bool(verify_connection)
        )
        connection_checked = bool(configured and dependency_available and should_verify_connection)
        connection_ok = None
        connection_error = None
        ready = configured and dependency_available
        fallback_reason = None
        if not configured:
            fallback_reason = "missing_settings:neo4j_uri"
        elif not dependency_available:
            fallback_reason = "missing_dependency:neo4j"
        elif connection_checked:
            connection_ok, connection_error = self._probe_connection(settings)
            ready = bool(connection_ok)
            if not connection_ok:
                fallback_reason = "connection_failed:neo4j"
        return {
            "configured": configured,
            "ready": ready,
            "dependency": "neo4j",
            "dependency_available": dependency_available,
            "uri": _redact_url(uri),
            "database": database or None,
            "auth_configured": bool(
                getattr(settings, "neo4j_user", "") and getattr(settings, "neo4j_password", None)
            ),
            "timeout_seconds": max(1.0, float(getattr(settings, "neo4j_timeout_seconds", 15.0) or 15.0)),
            "connection_checked": connection_checked,
            "connection_ok": connection_ok,
            "connection_error": connection_error,
            "fallback_reason": fallback_reason,
            "local_docker_defaults": _local_docker_defaults_status(),
        }

    def import_graph(self, graph: Any, tickers: list[str] | None = None) -> dict:
        status = self.status(verify_connection=False)
        payload = graph.neo4j_import_payload(tickers)
        if not status["ready"]:
            return {
                "status": "not_configured" if not status["configured"] else "dependency_missing",
                "neo4j": status,
                "payload": payload,
            }

        settings = self.settings_provider()
        driver = None
        database = str(getattr(settings, "neo4j_database", "") or "").strip() or None
        try:
            driver = self._driver(settings)
            with driver.session(database=database) as session:
                for statement in payload["statements"]:
                    result = session.run(statement, payload["parameters"])
                    consume = getattr(result, "consume", None)
                    if callable(consume):
                        consume()
        except Exception as exc:
            return {
                "status": "import_failed",
                "neo4j": {
                    **status,
                    "fallback_reason": "neo4j_import_failed",
                },
                "payload": payload,
                "error": str(exc) or exc.__class__.__name__,
                "retryable": True,
            }
        finally:
            if driver is not None:
                close = getattr(driver, "close", None)
                if callable(close):
                    close()

        return {
            "status": "imported",
            "neo4j": status,
            "node_count": len(payload["parameters"]["nodes"]),
            "structural_edge_count": len(payload["parameters"]["structural_edges"]),
            "peer_edge_count": len(payload["parameters"]["peer_edges"]),
            "statement_count": len(payload["statements"]),
            "note": payload["note"],
        }

    def _probe_connection(self, settings: Any) -> tuple[bool, str | None]:
        driver = None
        database = str(getattr(settings, "neo4j_database", "") or "").strip() or None
        try:
            driver = self._driver(settings)
            with driver.session(database=database) as session:
                result = session.run("RETURN 1 AS ok")
                consume = getattr(result, "consume", None)
                if callable(consume):
                    consume()
            return True, None
        except Exception as exc:
            return False, str(exc) or exc.__class__.__name__
        finally:
            if driver is not None:
                close = getattr(driver, "close", None)
                if callable(close):
                    close()

    def _driver(self, settings: Any):
        uri = str(getattr(settings, "neo4j_uri", "") or "").strip()
        auth = _neo4j_auth(settings)
        if self.driver_factory is not None:
            return self.driver_factory(uri, auth=auth)
        try:
            from neo4j import GraphDatabase
        except Exception as exc:  # pragma: no cover - guarded by status in normal path
            raise RuntimeError("Neo4j driver is not available") from exc
        timeout = max(1.0, float(getattr(settings, "neo4j_timeout_seconds", 15.0) or 15.0))
        return GraphDatabase.driver(
            uri,
            auth=auth,
            connection_timeout=timeout,
            connection_acquisition_timeout=timeout,
        )

    def _dependency_available(self) -> bool:
        try:
            return bool(self.dependency_checker("neo4j"))
        except Exception:
            return False


def _neo4j_auth(settings: Any):
    user = str(getattr(settings, "neo4j_user", "") or "").strip()
    password = getattr(settings, "neo4j_password", None)
    if user and password:
        return (user, password)
    return None


def _module_available(module_name: str) -> bool:
    return find_spec(module_name) is not None


def _local_docker_defaults_status() -> dict:
    return {
        "compose_service": "neo4j",
        "default_uri": LOCAL_NEO4J_ENV_DEFAULTS["NEO4J_URI"],
        "default_user": LOCAL_NEO4J_ENV_DEFAULTS["NEO4J_USER"],
        "default_database": LOCAL_NEO4J_ENV_DEFAULTS["NEO4J_DATABASE"],
        "env_keys": list(LOCAL_NEO4J_ENV_DEFAULTS),
        "one_click_start": "start_system.command",
        "cli_start": ".venv/bin/python scripts/start_system.py --start-dependencies",
        "note": "One-click startup applies these defaults to the spawned API/Streamlit process without editing .env.",
    }


def _redact_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.password is None:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"
    return parsed._replace(netloc=netloc).geturl()
