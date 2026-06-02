from __future__ import annotations

from app.services.upgrade_audit import audit_upgrade_capabilities


def _fake_status(overrides: dict | None = None) -> dict:
    matrix = {
        "ai_rag": {
            "multilingual_embedding": {"status": "ready", "evidence": {}},
            "llm_sdk_and_fallback": {"status": "ready", "evidence": {}},
            "hybrid_search": {"status": "ready", "evidence": {}},
            "reranking": {"status": "ready", "evidence": {}},
            "graphrag_context": {"status": "ready", "evidence": {}},
            "neo4j_payload_export": {"status": "ready", "evidence": {}},
            "neo4j_import": {"status": "degraded", "evidence": {"fallback_reason": "missing_settings:neo4j_uri"}},
        },
        "architecture": {
            "thin_api_controller": {"status": "ready", "evidence": {}},
            "workflow_orchestration": {"status": "ready", "evidence": {}},
            "database_migrations": {"status": "ready", "evidence": {}},
        },
        "data_business_logic": {
            "market_data_cache": {"status": "ready", "evidence": {}},
            "market_data_provider_fallback": {"status": "ready", "evidence": {}},
            "company_filing_fetch_hardening": {"status": "ready", "evidence": {}},
            "company_filing_pdf_table_parser_runtime": {"status": "ready", "evidence": {}},
            "company_filing_browser_or_proxy_fallback": {"status": "ready", "evidence": {}},
            "company_filing_cache": {"status": "ready", "evidence": {}},
            "source_quality_weighting": {"status": "ready", "evidence": {}},
        },
    }
    for path, value in (overrides or {}).items():
        area, capability = path.split(".")
        matrix[area][capability] = value
    return {"upgrade_capability_matrix": matrix}


def test_upgrade_audit_treats_live_neo4j_import_as_optional_by_default() -> None:
    audit = audit_upgrade_capabilities(_fake_status())

    assert audit["overall_status"] == "caution"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "caution"
    assert audit["summary"]["implementation_status"] == "ready"
    assert audit["summary"]["deployment_status"] == "caution"
    assert audit["summary"]["failures"] == 0
    assert audit["summary"]["warnings"] == 1
    warning = audit["warnings"][0]
    assert warning["capability"] == "neo4j_import"
    assert warning["optional"] is True
    assert warning["external_integration"] is True


def test_upgrade_audit_can_require_external_integrations_in_strict_mode() -> None:
    audit = audit_upgrade_capabilities(_fake_status(), strict_external=True)

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "failed"
    assert audit["summary"]["failures"] == 1
    assert audit["failures"][0]["capability"] == "neo4j_import"
    assert audit["failures"][0]["optional"] is False
    assert audit["failures"][0]["external_integration"] is True


def test_upgrade_audit_treats_company_filing_render_fallback_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_browser_or_proxy_fallback": {
                    "status": "not_configured",
                    "evidence": {"browser_or_proxy_fallback_configured": False},
                }
            }
        )
    )

    assert audit["overall_status"] == "caution"
    assert audit["implementation"]["status"] == "ready"
    assert audit["deployment"]["status"] == "caution"
    warning = next(
        item
        for item in audit["warnings"]
        if item["capability"] == "company_filing_browser_or_proxy_fallback"
    )
    assert warning["capability"] == "company_filing_browser_or_proxy_fallback"
    assert warning["optional"] is True
    assert warning["external_integration"] is True


def test_upgrade_audit_treats_pdf_table_parser_runtime_as_deployment_hardening() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status(
            {
                "data_business_logic.company_filing_pdf_table_parser_runtime": {
                    "status": "not_configured",
                    "evidence": {
                        "pdf_extract_tables": True,
                        "pdf_table_parser_available": False,
                    },
                }
            }
        )
    )

    assert audit["overall_status"] == "caution"
    warning = next(
        item
        for item in audit["warnings"]
        if item["capability"] == "company_filing_pdf_table_parser_runtime"
    )
    assert warning["optional"] is True
    assert warning["external_integration"] is True


def test_upgrade_audit_fails_required_capability_regression() -> None:
    audit = audit_upgrade_capabilities(
        _fake_status({"ai_rag.reranking": {"status": "degraded", "evidence": {"fallback_reason": "keyword"}}})
    )

    assert audit["overall_status"] == "failed"
    assert audit["implementation"]["status"] == "failed"
    assert audit["deployment"]["status"] == "caution"
    assert any(check["capability"] == "reranking" for check in audit["failures"])
    assert audit["areas"]["ai_rag"]["failures"] == 1
