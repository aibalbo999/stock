from __future__ import annotations

from collections.abc import Callable
from typing import Any


DISCOVERY_COMPATIBILITY_HELPER_NAMES = (
    "ingest_dynamic_news_urls",
    "run_topic_discovery_ingestion",
    "discover_topic_with_timeout",
)


def discovery_compatibility_helper_namespace(
    api_compatibility_provider: Callable[[], Any],
) -> dict[str, object]:
    def api_compatibility() -> Any:
        return api_compatibility_provider()

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

    helpers = locals()
    return {name: helpers[name] for name in DISCOVERY_COMPATIBILITY_HELPER_NAMES}
