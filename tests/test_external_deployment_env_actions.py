from __future__ import annotations

from app.services.external_deployment_env_actions import (
    external_env_key_actions,
    external_env_key_next_step,
    external_env_maintenance_action,
    external_env_resolution_type,
    external_env_summary,
)


def test_external_env_actions_surface_defaulted_neo4j_local_rules() -> None:
    item = {
        "area": "ai_rag",
        "capability": "neo4j_import",
        "evidence": {"fallback_reason": "missing_settings:neo4j_uri"},
        "remediation": "設定 NEO4J_URI / 帳密並啟動 Neo4j。",
    }

    summary = external_env_summary(item)
    actions = external_env_key_actions(item, summary)

    assert ("NEO4J_URI", "缺少") in actions
    assert ("NEO4J_USER", "建議") in actions
    assert external_env_resolution_type(item, "NEO4J_URI", "neo4j://localhost:7687") == (
        "本機可套用"
    )
    assert (
        external_env_maintenance_action(
            item,
            "NEO4J_URI",
            "neo4j://localhost:7687",
            "本機可套用",
        )
        == ".venv/bin/python scripts/start_system.py --start-dependencies"
    )
    assert external_env_key_next_step(item, "NEO4J_URI", "缺少") == (
        "補齊 NEO4J_URI 後重跑對應 smoke。"
    )


def test_external_env_actions_classify_managed_unlocker_and_secret_rules() -> None:
    item = {
        "area": "data_business_logic",
        "capability": "company_filing_high_risk_unlocker",
        "evidence": {
            "configured_env_keys": ["COMPANY_FILING_BROWSER_RENDER_PROVIDER"],
            "recommended_env": [
                "COMPANY_FILING_BROWSER_RENDER_PROVIDER=scrapingbee",  # pragma: allowlist secret
                "COMPANY_FILING_BROWSER_RENDER_URL=https://app.scrapingbee.com/api/v1",
                "COMPANY_FILING_BROWSER_RENDER_TOKEN=<token>",
            ],
        },
        "remediation": "設定 FlareSolverr、ScrapingBee、BrightData 或 rotating proxy。",
    }

    summary = external_env_summary(item)
    actions = external_env_key_actions(item, summary)

    assert ("COMPANY_FILING_BROWSER_RENDER_PROVIDER", "建議") in actions
    assert ("COMPANY_FILING_BROWSER_RENDER_URL", "建議") in actions
    assert (
        external_env_resolution_type(
            item,
            "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
            "scrapingbee",
        )
        == "外部服務選配"
    )
    assert (
        external_env_resolution_type(
            item,
            "COMPANY_FILING_BROWSER_RENDER_PROVIDER",
            "flaresolverr",
        )
        == "本機可套用"
    )
    assert (
        external_env_resolution_type(
            item,
            "COMPANY_FILING_BROWSER_RENDER_TOKEN",
            "<token>",
        )
        == "需人工密鑰"
    )
    assert (
        external_env_maintenance_action(
            item,
            "COMPANY_FILING_BROWSER_RENDER_TOKEN",
            "<token>",
            "需人工密鑰",
        )
        == "手動補 .env 或 secret manager；不由維護操作寫入。"
    )


def test_external_env_actions_classify_structured_api_and_manual_values() -> None:
    structured_item = {
        "area": "data_business_logic",
        "capability": "company_filing_structured_api_fallback",
    }
    generic_item = {"area": "data_business_logic", "capability": "custom"}

    assert (
        external_env_resolution_type(
            structured_item,
            "COMPANY_FILING_STRUCTURED_API_PROVIDER",
            "tej",
        )
        == "外部資料源設定"
    )
    assert (
        external_env_resolution_type(
            structured_item,
            "COMPANY_FILING_STRUCTURED_API_URL",
            "<provider-json-endpoint>",
        )
        == "外部資料源設定"
    )
    assert (
        external_env_resolution_type(
            generic_item,
            "COMPANY_FILING_PROXY_URLS",
            "<rotating-proxy-list>",
        )
        == "外部服務選配"
    )
    assert external_env_resolution_type(generic_item, "CUSTOM_URL", "<manual-url>") == (
        "需人工設定"
    )
    assert (
        external_env_maintenance_action(
            structured_item,
            "COMPANY_FILING_STRUCTURED_API_URL",
            "<provider-json-endpoint>",
            "外部資料源設定",
        )
        == "手動補 .env 或部署 secret 後重跑外部設定缺口診斷。"
    )
