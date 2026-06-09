from __future__ import annotations

from app.services.external_deployment_env_resolution import (
    external_deployment_env_resolution_rows_from_key_rows,
)


def test_external_deployment_env_resolution_groups_local_and_manual_rows() -> None:
    rows = [
        {
            "優先級": "P1",
            "能力": "外部 Neo4j 匯入連線",
            "設定鍵": "NEO4J_URI",
            "狀態": "缺少",
            "處理類型": "本機可套用",
            "維護動作": ".venv/bin/python scripts/start_system.py --start-dependencies",
            "驗證指令": ".venv/bin/python scripts/upgrade_audit.py --local-neo4j-defaults --json",
        },
        {
            "優先級": "P1",
            "能力": "外部 Neo4j 匯入連線",
            "設定鍵": "NEO4J_PASSWORD",
            "狀態": "建議",
            "處理類型": "本機可套用",
            "維護動作": ".venv/bin/python scripts/start_system.py --start-dependencies",
            "驗證指令": ".venv/bin/python scripts/upgrade_audit.py --local-neo4j-defaults --json",
        },
        {
            "優先級": "P2",
            "能力": "公司文件結構化 API 備援",
            "設定鍵": "COMPANY_FILING_STRUCTURED_API_TOKEN",
            "狀態": "缺少",
            "處理類型": "需人工密鑰",
            "維護動作": "手動補 .env 或 secret manager；不由維護操作寫入。",
            "驗證指令": ".venv/bin/python scripts/structured_company_filing_smoke.py --json",
        },
    ]

    resolution_rows = external_deployment_env_resolution_rows_from_key_rows(rows)
    resolution_by_capability = {row["能力"]: row for row in resolution_rows}

    neo4j = resolution_by_capability["外部 Neo4j 匯入連線"]
    assert neo4j["處理策略"] == "可用本機維護操作"
    assert neo4j["缺口數"] == 2
    assert neo4j["缺少"] == 1
    assert neo4j["建議"] == 1
    assert neo4j["本機可套用"] == 2
    assert neo4j["需人工處理"] == 0
    assert neo4j["設定鍵"] == "NEO4J_URI、NEO4J_PASSWORD"
    assert neo4j["本機指令"] == ".venv/bin/python scripts/start_system.py --start-dependencies"
    assert neo4j["建議動作"] == ".venv/bin/python scripts/start_system.py --start-dependencies"

    structured = resolution_by_capability["公司文件結構化 API 備援"]
    assert structured["處理策略"] == "需人工密鑰"
    assert structured["需人工密鑰"] == 1
    assert structured["手動設定鍵"] == "COMPANY_FILING_STRUCTURED_API_TOKEN"
    assert structured["建議動作"] == "手動補 .env 或 secret manager；不由維護操作寫入。"
