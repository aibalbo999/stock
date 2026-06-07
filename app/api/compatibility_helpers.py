from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


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

    def safe_mark_run_failed(run_id, error):
        return api_compatibility().safe_mark_run_failed(run_id, error)

    def safe_update_run_success(run_id, payload, report_id):
        return api_compatibility().safe_update_run_success(run_id, payload, report_id)

    def load_report_follow_up_context(report_id):
        return api_compatibility().load_report_follow_up_context(report_id)

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

    async def prepare_follow_up_report_context(context, request, actions):
        return await api_compatibility().prepare_follow_up_report_context(context, request, actions)

    async def refresh_market_data_for_report(request):
        return await api_compatibility().refresh_market_data_for_report(request)

    async def ingest_dynamic_news_urls(urls, limit_per_query, start_date, end_date):
        return await api_compatibility().ingest_dynamic_news_urls(
            urls,
            limit_per_query,
            start_date,
            end_date,
        )

    async def run_topic_discovery_ingestion(
        payload,
        service,
        plan,
        limit_per_query,
        evidence_limit,
        max_queries,
        document_limit,
    ):
        return await api_compatibility().run_topic_discovery_ingestion(
            payload,
            service,
            plan,
            limit_per_query,
            evidence_limit,
            max_queries,
            document_limit,
        )

    async def discover_topic_with_timeout(service, topic, timeout=75):
        return await api_compatibility().discover_topic_with_timeout(service, topic, timeout)

    def get_report_follow_up_plan(report_id):
        return api_compatibility().get_report_follow_up_plan(report_id)

    async def maybe_auto_start_required_follow_up(report_id, run_in_background=True):
        return await api_compatibility().maybe_auto_start_required_follow_up(
            report_id,
            run_in_background,
        )

    async def run_required_follow_up_background(report_id, payload):
        await api_compatibility().run_required_follow_up_background(report_id, payload)

    async def run_report_follow_up(report_id, payload=None):
        return await api_compatibility().run_report_follow_up(report_id, payload)

    helpers = locals()
    return {name: helpers[name] for name in LEGACY_DELEGATE_EXPORT_NAMES}
