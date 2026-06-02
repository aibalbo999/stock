from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.services.supply_chain_graph_api import SupplyChainGraphApiService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export or import the supply-chain GraphRAG payload for Neo4j.")
    parser.add_argument(
        "--tickers",
        default="",
        help="Optional comma-separated ticker list. When omitted, exports/imports the full graph.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Neo4j Cypher statements and parameters without connecting to Neo4j.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path for the dry-run or import result.",
    )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    service: SupplyChainGraphApiService | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    graph_service = service or SupplyChainGraphApiService()
    if args.dry_run:
        result = {
            "status": "dry_run",
            "payload": graph_service.graph_neo4j_payload(args.tickers),
        }
    else:
        result = graph_service.import_graph_to_neo4j(args.tickers)

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result.get("status") in {"dry_run", "imported"} else 2


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
