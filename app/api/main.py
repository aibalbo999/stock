from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from app.api.app_factory import create_app
from app.api.compatibility_exports import (
    COMPATIBILITY_EXPORT_NAMES,
    LEGACY_HELPER_EXPORT_NAMES,
    compatibility_export_namespace,
)
from app.api.dependencies import build_service_factory_dependencies
from app.api.service_factory import ApiServiceFactory
from app.services.api_compatibility import ApiCompatibilityService


LOGGER = logging.getLogger(__name__)

_compatibility_exports = compatibility_export_namespace()
globals().update(_compatibility_exports)
init_db = _compatibility_exports["init_db"]
candidate_revalidation = _compatibility_exports["candidate_revalidation"]
FollowUpRunRequest = _compatibility_exports["FollowUpRunRequest"]

__all__ = [
    *LEGACY_HELPER_EXPORT_NAMES,
    "app",
    "_api_services",
]


def sufficient_company_filing_tickers(tickers):
    return _api_compatibility.sufficient_company_filing_tickers(tickers)


def count_sufficient_company_filings(tickers):
    return _api_compatibility.count_sufficient_company_filings(tickers)


def apply_company_filing_gate_to_candidate_payload(candidates):
    return _api_compatibility.apply_company_filing_gate_to_candidate_payload(
        candidates,
        sufficient_tickers_provider=sufficient_company_filing_tickers,
    )


def safe_mark_run_failed(run_id, error):
    return _api_compatibility.safe_mark_run_failed(run_id, error)


def safe_update_run_success(run_id, payload, report_id):
    return _api_compatibility.safe_update_run_success(run_id, payload, report_id)


def load_report_follow_up_context(report_id):
    return _api_compatibility.load_report_follow_up_context(report_id)


def revalidate_candidate_whitelist(run_payload, fallback_candidates, limit=500):
    return _api_compatibility.revalidate_candidate_whitelist(
        run_payload,
        fallback_candidates,
        limit,
    )


def preserve_previous_supported_candidates(current_candidates, previous_candidates):
    return _api_compatibility.preserve_previous_supported_candidates(
        current_candidates,
        previous_candidates,
    )


def mark_unavailable_candidates_after_revalidation(candidates, document_count):
    return _api_compatibility.mark_unavailable_candidates_after_revalidation(
        candidates,
        document_count,
    )


def candidate_revalidation_queries(plan, topic="", limit=80):
    return _api_compatibility.candidate_revalidation_queries(plan, topic, limit)


def collect_revalidation_documents(repository, queries, limit):
    return _api_compatibility.collect_revalidation_documents(repository, queries, limit)


def dedupe_documents(documents):
    return _api_compatibility.dedupe_documents(documents)


def persist_candidate_entity_matches(plan, candidates, documents):
    return _api_compatibility.persist_candidate_entity_matches(plan, candidates, documents)


def dedupe_strings(values, limit):
    return _api_compatibility.dedupe_strings(values, limit)


async def prepare_follow_up_report_context(context, request, actions):
    return await _api_compatibility.prepare_follow_up_report_context(context, request, actions)


async def refresh_market_data_for_report(request):
    return await _api_compatibility.refresh_market_data_for_report(request)


async def ingest_dynamic_news_urls(urls, limit_per_query, start_date, end_date):
    return await _api_compatibility.ingest_dynamic_news_urls(
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
    return await _api_compatibility.run_topic_discovery_ingestion(
        payload,
        service,
        plan,
        limit_per_query,
        evidence_limit,
        max_queries,
        document_limit,
    )


async def discover_topic_with_timeout(service, topic, timeout=75):
    return await _api_compatibility.discover_topic_with_timeout(service, topic, timeout)


def get_report_follow_up_plan(report_id):
    return _api_compatibility.get_report_follow_up_plan(report_id)


async def maybe_auto_start_required_follow_up(report_id, run_in_background=True):
    return await _api_compatibility.maybe_auto_start_required_follow_up(
        report_id,
        run_in_background,
    )


async def run_required_follow_up_background(report_id, payload):
    await _api_compatibility.run_required_follow_up_background(report_id, payload)


async def run_report_follow_up(report_id, payload=None):
    return await _api_compatibility.run_report_follow_up(report_id, payload)


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


_api_services = ApiServiceFactory(build_service_factory_dependencies(globals()), logger=LOGGER)
_api_compatibility = ApiCompatibilityService(
    api_services=_api_services,
    candidate_revalidation_module=candidate_revalidation,
    follow_up_run_request_cls=FollowUpRunRequest,
    logger=LOGGER,
)

app = create_app(
    api_services=_api_services,
    lifespan=lifespan,
    get_follow_up_plan_func=get_report_follow_up_plan,
    auto_start_follow_up_func=lambda report_id: maybe_auto_start_required_follow_up(report_id),
    run_follow_up_func=lambda report_id, payload=None: run_report_follow_up(report_id, payload),
)


def __dir__() -> list[str]:
    return sorted({*globals(), *COMPATIBILITY_EXPORT_NAMES})
