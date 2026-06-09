from __future__ import annotations

from app.services.optimization_domains import (
    OPTIMIZATION_DOMAINS,
    OptimizationCapabilityRef,
    OptimizationDomain,
)


def test_optimization_domains_catalog_preserves_goal_domain_order_and_types() -> None:
    assert isinstance(OPTIMIZATION_DOMAINS[0], OptimizationDomain)
    assert isinstance(OPTIMIZATION_DOMAINS[0].capability_refs[0], OptimizationCapabilityRef)
    assert [domain.id for domain in OPTIMIZATION_DOMAINS] == [
        "architecture_uiux",
        "codebase_maintainability",
        "data_pipeline_scraping",
        "ai_rag_graphrag",
    ]


def test_optimization_domains_catalog_marks_external_optional_cost_profiles() -> None:
    refs = {
        ref.capability: ref for domain in OPTIMIZATION_DOMAINS for ref in domain.capability_refs
    }

    assert refs["company_filing_structured_api_fallback"].optional is True
    assert refs["company_filing_structured_api_fallback"].external is True
    assert refs["company_filing_structured_api_fallback"].action_type == "paid_external"
    assert "TEJ" in refs["company_filing_structured_api_fallback"].next_action
    assert refs["neo4j_import"].action_type == "free_local_or_external_config"
    assert refs["visual_rag"].action_type == "quota_or_external"
