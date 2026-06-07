from __future__ import annotations

import re
from collections.abc import Callable, Mapping
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
            "smoke_cli": (
                ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
            ),
            "import_smoke_cli": (
                ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
                "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json"
            ),
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

    def execute_read_query(self, plan: dict[str, Any], *, max_records: int = 25) -> dict:
        safe_max_records = max(1, min(100, int(max_records or 25)))
        validation = _validate_live_read_plan(plan)
        if not validation["valid"]:
            return {
                "status": "rejected",
                "validation": validation,
                "plan": _redact_plan_for_response(plan),
                "record_limit": safe_max_records,
            }

        status = self.status(verify_connection=False)
        if not status["ready"]:
            return {
                "status": "not_configured" if not status["configured"] else "dependency_missing",
                "neo4j": status,
                "validation": validation,
                "plan": _redact_plan_for_response(plan),
                "record_limit": safe_max_records,
            }

        cypher = str(plan.get("cypher") or "").strip()
        parameters = _clamped_query_parameters(
            plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {},
            max_records=safe_max_records,
        )
        settings = self.settings_provider()
        driver = None
        database = str(getattr(settings, "neo4j_database", "") or "").strip() or None
        rows: list[dict[str, Any]] = []
        summary_payload: dict[str, Any] = {}
        try:
            driver = self._driver(settings)
            with driver.session(database=database) as session:
                result = session.run(cypher, parameters)
                for index, record in enumerate(result):
                    if index >= safe_max_records:
                        break
                    rows.append(_serialize_neo4j_record(record))
                consume = getattr(result, "consume", None)
                if callable(consume):
                    summary_payload = _serialize_neo4j_summary(consume())
        except Exception as exc:
            return {
                "status": "query_failed",
                "neo4j": {
                    **status,
                    "fallback_reason": "neo4j_read_query_failed",
                },
                "validation": validation,
                "plan": _redact_plan_for_response(plan),
                "record_limit": safe_max_records,
                "error": str(exc) or exc.__class__.__name__,
                "retryable": True,
            }
        finally:
            if driver is not None:
                close = getattr(driver, "close", None)
                if callable(close):
                    close()

        return {
            "status": "executed",
            "neo4j": status,
            "validation": validation,
            "plan": _redact_plan_for_response(plan),
            "record_limit": safe_max_records,
            "row_count": len(rows),
            "rows": rows,
            "summary": summary_payload,
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


def _validate_live_read_plan(plan: dict[str, Any]) -> dict:
    cypher = str(plan.get("cypher") or "").strip()
    parameters = plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {}
    plan_validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
    errors: list[str] = []
    if plan_validation.get("valid") is not True:
        errors.append("guarded_plan_validation_required")
    if not cypher.upper().startswith("MATCH "):
        errors.append("cypher_must_start_with_match")
    if ";" in cypher or "--" in cypher or "/*" in cypher:
        errors.append("cypher_must_not_contain_statement_separators_or_comments")
    upper_tokens = {token.upper() for token in re.findall(r"\b[A-Za-z_]+\b", cypher)}
    blocked_tokens = sorted(
        upper_tokens
        & {
            "ALTER",
            "CALL",
            "CREATE",
            "DELETE",
            "DENY",
            "DETACH",
            "DROP",
            "GRANT",
            "LOAD",
            "MERGE",
            "REMOVE",
            "REVOKE",
            "SET",
            "TERMINATE",
            "UNWIND",
        }
    )
    if blocked_tokens:
        errors.append("blocked_keywords:" + ",".join(blocked_tokens))
    uses_limit_parameter = bool(
        re.search(r"\bLIMIT\s+\$limit\b", cypher, flags=re.IGNORECASE)
    )
    if not uses_limit_parameter:
        errors.append("cypher_must_use_limit_parameter_for_live_execution")
    if "limit" not in parameters:
        errors.append("limit_parameter_required_for_live_execution")
    return {
        "valid": not errors,
        "errors": errors,
        "read_only": not any(error.startswith("blocked_keywords") for error in errors),
        "uses_limit_parameter": uses_limit_parameter,
    }


def _clamped_query_parameters(parameters: dict[str, Any], *, max_records: int) -> dict[str, Any]:
    clamped = dict(parameters)
    try:
        requested_limit = int(clamped.get("limit", max_records))
    except (TypeError, ValueError):
        requested_limit = max_records
    clamped["limit"] = max(1, min(max_records, requested_limit))
    return clamped


def _redact_plan_for_response(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": plan.get("intent"),
        "cypher": plan.get("cypher"),
        "parameters": plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {},
        "source": plan.get("source"),
        "validation": plan.get("validation") if isinstance(plan.get("validation"), dict) else {},
    }


def _serialize_neo4j_record(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        payload = dict(record)
    else:
        data = getattr(record, "data", None)
        if callable(data):
            payload = data()
        elif hasattr(record, "keys"):
            payload = {key: record[key] for key in record.keys()}
        else:
            return {"value": _serialize_neo4j_value(record)}
    return {str(key): _serialize_neo4j_value(value) for key, value in payload.items()}


def _serialize_neo4j_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _serialize_neo4j_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_neo4j_value(item) for item in value]
    if hasattr(value, "nodes") and hasattr(value, "relationships"):
        return {
            "type": "path",
            "nodes": [_serialize_neo4j_value(node) for node in value.nodes],
            "relationships": [
                _serialize_neo4j_value(relationship)
                for relationship in value.relationships
            ],
        }
    if hasattr(value, "labels") and hasattr(value, "items"):
        return {
            "type": "node",
            "element_id": getattr(value, "element_id", None),
            "labels": sorted(str(label) for label in getattr(value, "labels", [])),
            "properties": {
                str(key): _serialize_neo4j_value(item)
                for key, item in dict(value.items()).items()
            },
        }
    if hasattr(value, "type") and hasattr(value, "items"):
        return {
            "type": "relationship",
            "element_id": getattr(value, "element_id", None),
            "relationship_type": str(getattr(value, "type", "")),
            "start_element_id": getattr(getattr(value, "start_node", None), "element_id", None),
            "end_element_id": getattr(getattr(value, "end_node", None), "element_id", None),
            "properties": {
                str(key): _serialize_neo4j_value(item)
                for key, item in dict(value.items()).items()
            },
        }
    return str(value)


def _serialize_neo4j_summary(summary: Any) -> dict[str, Any]:
    if summary is None:
        return {}
    return {
        "result_available_after_ms": getattr(summary, "result_available_after", None),
        "result_consumed_after_ms": getattr(summary, "result_consumed_after", None),
        "query_type": getattr(summary, "query_type", None),
    }


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
