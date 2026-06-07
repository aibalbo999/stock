from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.api.compatibility_helper_candidate import candidate_compatibility_helper_namespace
from app.api.compatibility_helper_discovery import discovery_compatibility_helper_namespace
from app.api.compatibility_helper_followup import follow_up_compatibility_helper_namespace
from app.api.compatibility_helper_run_state import run_state_compatibility_helper_namespace


LEGACY_DELEGATE_EXPORT_NAMES = (
    "sufficient_company_filing_tickers",
    "count_sufficient_company_filings",
    "apply_company_filing_gate_to_candidate_payload",
    "safe_mark_run_failed",
    "safe_update_run_success",
    "load_report_follow_up_context",
    "revalidate_candidate_whitelist",
    "preserve_previous_supported_candidates",
    "mark_unavailable_candidates_after_revalidation",
    "candidate_revalidation_queries",
    "collect_revalidation_documents",
    "dedupe_documents",
    "persist_candidate_entity_matches",
    "dedupe_strings",
    "prepare_follow_up_report_context",
    "refresh_market_data_for_report",
    "ingest_dynamic_news_urls",
    "run_topic_discovery_ingestion",
    "discover_topic_with_timeout",
    "get_report_follow_up_plan",
    "maybe_auto_start_required_follow_up",
    "run_required_follow_up_background",
    "run_report_follow_up",
)


def compatibility_helper_namespace(
    api_compatibility_provider: Callable[[], Any],
    *,
    globals_provider: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, object]:
    """Build legacy helper functions without keeping their definitions in main.py."""

    helpers = {
        **candidate_compatibility_helper_namespace(
            api_compatibility_provider,
            globals_provider=globals_provider,
        ),
        **run_state_compatibility_helper_namespace(api_compatibility_provider),
        **follow_up_compatibility_helper_namespace(api_compatibility_provider),
        **discovery_compatibility_helper_namespace(api_compatibility_provider),
    }
    missing = [name for name in LEGACY_DELEGATE_EXPORT_NAMES if name not in helpers]
    if missing:
        raise RuntimeError("Compatibility helper namespace is missing: " + ", ".join(missing))
    return {name: helpers[name] for name in LEGACY_DELEGATE_EXPORT_NAMES}
