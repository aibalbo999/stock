from __future__ import annotations

from app.services.external_deployment_env_catalog import (
    EXTERNAL_ENV_CHECK_TARGETS,
    external_capability_env_defaults,
    external_env_compose_recommended_value,
    external_env_key_hint,
)


def test_external_env_catalog_exposes_hints_and_capability_defaults() -> None:
    structured_keys = external_capability_env_defaults(
        "data_business_logic",
        "company_filing_structured_api_fallback",
    )

    assert structured_keys == (
        "COMPANY_FILING_STRUCTURED_API_PROVIDER",
        "COMPANY_FILING_STRUCTURED_API_URL",
        "COMPANY_FILING_STRUCTURED_API_TOKEN",
    )
    assert external_env_key_hint("COMPANY_FILING_STRUCTURED_API_PROVIDER") == {
        "default": "tej",
        "scope": "公司文件結構化 API 備援",
    }
    assert external_env_key_hint("UNKNOWN_KEY") == {}
    assert EXTERNAL_ENV_CHECK_TARGETS == ("host", "compose")


def test_external_env_catalog_maps_compose_defaults() -> None:
    assert (
        external_env_compose_recommended_value("NEO4J_URI", "neo4j://localhost:7687", {})
        == "neo4j://neo4j:7687"
    )
    assert (
        external_env_compose_recommended_value(
            "COMPANY_FILING_BROWSER_RENDER_URL",
            "http://127.0.0.1:8191/v1",
            {"COMPANY_FILING_BROWSER_RENDER_URL": "http://flaresolverr:8191/v1"},
        )
        == "http://flaresolverr:8191/v1"
    )
    assert external_env_compose_recommended_value("CUSTOM_URL", "https://example.com", {}) == (
        "https://example.com"
    )
