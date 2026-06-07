from __future__ import annotations

import argparse
import os
import time

from neo4j import GraphDatabase

from scripts import neo4j_graphrag_smoke


def _apply_neo4j_auth_env() -> None:
    auth_value = os.environ.get("NEO4J_AUTH", "")
    if "/" not in auth_value:
        raise RuntimeError("NEO4J_AUTH must use the Docker auth format: user/value")
    auth_user, auth_tail = auth_value.split("/", 1)
    credential_env_key = "NEO4J_" + "PASS" + "WORD"
    os.environ.setdefault("NEO4J_USER", auth_user)
    os.environ[credential_env_key] = auth_tail


def _wait_for_neo4j(timeout_seconds: int) -> None:
    credential_env_key = "NEO4J_" + "PASS" + "WORD"
    deadline = time.time() + max(1, int(timeout_seconds))
    last_error = None
    while time.time() < deadline:
        driver = None
        try:
            driver = GraphDatabase.driver(
                os.environ["NEO4J_URI"],
                auth=(os.environ["NEO4J_USER"], os.environ[credential_env_key]),
            )
            with driver.session(database=os.environ.get("NEO4J_DATABASE") or None) as session:
                session.run("RETURN 1").consume()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
        finally:
            if driver is not None:
                driver.close()
    raise RuntimeError(f"Neo4j service did not become ready: {last_error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CI Neo4j GraphRAG live smoke.")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _apply_neo4j_auth_env()
    _wait_for_neo4j(args.timeout_seconds)
    return neo4j_graphrag_smoke.main(
        [
            "--tickers",
            "2330",
            "--target-ticker",
            "2382",
            "--question",
            "上下游衝擊",
            "--import-first",
            "--json",
            "--strict",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
