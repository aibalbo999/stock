from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


CANDIDATE_COMPATIBILITY_HELPER_NAMES = (
    "sufficient_company_filing_tickers",
    "count_sufficient_company_filings",
    "apply_company_filing_gate_to_candidate_payload",
    "revalidate_candidate_whitelist",
    "preserve_previous_supported_candidates",
    "mark_unavailable_candidates_after_revalidation",
    "candidate_revalidation_queries",
    "collect_revalidation_documents",
    "dedupe_documents",
    "persist_candidate_entity_matches",
    "dedupe_strings",
)


def candidate_compatibility_helper_namespace(
    api_compatibility_provider: Callable[[], Any],
    *,
    globals_provider: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, object]:
    def api_compatibility() -> Any:
        return api_compatibility_provider()

    def sufficient_company_filing_tickers(tickers):
        return api_compatibility().sufficient_company_filing_tickers(tickers)

    def count_sufficient_company_filings(tickers):
        return api_compatibility().count_sufficient_company_filings(tickers)

    def apply_company_filing_gate_to_candidate_payload(candidates):
        sufficient_tickers_provider = sufficient_company_filing_tickers
        if globals_provider is not None:
            sufficient_tickers_provider = globals_provider().get(
                "sufficient_company_filing_tickers",
                sufficient_tickers_provider,
            )
        return api_compatibility().apply_company_filing_gate_to_candidate_payload(
            candidates,
            sufficient_tickers_provider=sufficient_tickers_provider,
        )

    def revalidate_candidate_whitelist(run_payload, fallback_candidates, limit=500):
        return api_compatibility().revalidate_candidate_whitelist(
            run_payload,
            fallback_candidates,
            limit,
        )

    def preserve_previous_supported_candidates(current_candidates, previous_candidates):
        return api_compatibility().preserve_previous_supported_candidates(
            current_candidates,
            previous_candidates,
        )

    def mark_unavailable_candidates_after_revalidation(candidates, document_count):
        return api_compatibility().mark_unavailable_candidates_after_revalidation(
            candidates,
            document_count,
        )

    def candidate_revalidation_queries(plan, topic="", limit=80):
        return api_compatibility().candidate_revalidation_queries(plan, topic, limit)

    def collect_revalidation_documents(repository, queries, limit):
        return api_compatibility().collect_revalidation_documents(repository, queries, limit)

    def dedupe_documents(documents):
        return api_compatibility().dedupe_documents(documents)

    def persist_candidate_entity_matches(plan, candidates, documents):
        return api_compatibility().persist_candidate_entity_matches(plan, candidates, documents)

    def dedupe_strings(values, limit):
        return api_compatibility().dedupe_strings(values, limit)

    helpers = locals()
    return {name: helpers[name] for name in CANDIDATE_COMPATIBILITY_HELPER_NAMES}
