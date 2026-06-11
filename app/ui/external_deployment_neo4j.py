from __future__ import annotations

from app.ui.external_deployment_common import external_deployment_item_by_capability


def local_neo4j_operation_rows(upgrade_audit: dict) -> list[dict]:
    import_item = external_deployment_item_by_capability(upgrade_audit, "neo4j_import")
    cypher_item = external_deployment_item_by_capability(
        upgrade_audit,
        "graphrag_live_cypher_query",
    )
    if not (import_item or cypher_item):
        return []
    import_evidence = (
        import_item.get("evidence")
        if isinstance(import_item.get("evidence"), dict)
        else {}
    )
    cypher_evidence = (
        cypher_item.get("evidence")
        if isinstance(cypher_item.get("evidence"), dict)
        else {}
    )
    local_defaults = (
        import_evidence.get("local_docker_defaults")
        if isinstance(import_evidence.get("local_docker_defaults"), dict)
        else {}
    )
    neo4j_ready = bool(
        import_evidence.get("ready")
        or import_evidence.get("connection_ok")
        or cypher_evidence.get("neo4j_ready")
    )
    start_command = str(
        local_defaults.get("cli_start")
        or ".venv/bin/python scripts/start_system.py --start-dependencies"
    )
    return [
        {
            "項目": "一鍵啟動",
            "狀態": "可重跑" if neo4j_ready else "待啟動",
            "指令": start_command,
            "說明": "啟動本機 Neo4j，並在同一個 API/Streamlit 程序套用 docker-compose 預設連線值。",
        },
        {
            "項目": "本機稽核",
            "狀態": "已就緒" if neo4j_ready else "待驗證",
            "指令": (
                ".venv/bin/python scripts/upgrade_audit.py "
                "--local-neo4j-defaults --wait-local-neo4j 20 --json"
            ),
            "說明": "等待 localhost:7687 後套用本機 Neo4j defaults；不改寫 .env。",
        },
        {
            "項目": "圖譜匯入預檢",
            "狀態": "可執行" if import_evidence.get("payload_export_ready") else "檢查",
            "指令": neo4j_payload_dry_run_command(import_evidence, cypher_evidence),
            "說明": _neo4j_payload_summary(import_evidence),
        },
        {
            "項目": "Live 查詢驗證",
            "狀態": "可執行" if neo4j_ready else "需 Neo4j",
            "指令": neo4j_live_smoke_command(import_evidence, cypher_evidence),
            "說明": "驗證 guarded read-only Cypher plan 與 Neo4j 查詢契約。",
        },
        {
            "項目": "先匯入再查詢驗證",
            "狀態": "可執行" if neo4j_ready else "需 Neo4j",
            "指令": neo4j_import_first_smoke_command(import_evidence, cypher_evidence),
            "說明": "先匯入目前 GraphRAG payload，再執行 guarded live Cypher 查詢。",
        },
        {
            "項目": "容器診斷",
            "狀態": "必要時",
            "指令": "docker compose ps neo4j && docker compose logs neo4j",
            "說明": _local_neo4j_fallback_detail(import_evidence, cypher_evidence),
        },
    ]


def neo4j_payload_dry_run_command(import_evidence: dict, cypher_evidence: dict) -> str:
    return str(
        import_evidence.get("payload_dry_run_cli")
        or cypher_evidence.get("payload_dry_run_cli")
        or ".venv/bin/python -m scripts.import_supply_chain_graph_neo4j --dry-run"
    )


def neo4j_live_smoke_command(import_evidence: dict, cypher_evidence: dict) -> str:
    return str(
        cypher_evidence.get("smoke_cli")
        or import_evidence.get("smoke_cli")
        or (
            ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
            "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --json"
        )
    )


def neo4j_import_first_smoke_command(import_evidence: dict, cypher_evidence: dict) -> str:
    return str(
        import_evidence.get("import_smoke_cli")
        or cypher_evidence.get("import_smoke_cli")
        or (
            ".venv/bin/python scripts/neo4j_graphrag_smoke.py "
            "--tickers 2330 --target-ticker 2382 --question 上下游衝擊 --import-first --json"
        )
    )


def _neo4j_payload_summary(import_evidence: dict) -> str:
    if not import_evidence.get("payload_export_ready"):
        return "GraphRAG payload 尚未可匯出；請先檢查 /supply-chain/graph/neo4j。"
    node_count = int(import_evidence.get("payload_node_count") or 0)
    structural_edges = int(import_evidence.get("payload_structural_edge_count") or 0)
    peer_edges = int(import_evidence.get("payload_peer_edge_count") or 0)
    statements = int(import_evidence.get("payload_statement_count") or 0)
    return (
        f"payload 可用：nodes={node_count}、structural_edges={structural_edges}、"
        f"peer_edges={peer_edges}、statements={statements}。"
    )


def _local_neo4j_fallback_detail(import_evidence: dict, cypher_evidence: dict) -> str:
    if (
        import_evidence.get("ready")
        or import_evidence.get("connection_ok")
        or cypher_evidence.get("neo4j_ready")
    ):
        database = import_evidence.get("database") or "neo4j"
        return f"Neo4j 即時查詢與匯入已就緒；database={database}。"
    reason = (
        import_evidence.get("fallback_reason")
        or import_evidence.get("connection_error")
        or cypher_evidence.get("fallback_reason")
        or "missing_settings:neo4j_uri"
    )
    return f"目前只使用本機 GraphRAG 規劃與匯入資料預檢；Neo4j 即時查詢尚未就緒：{reason}。"
