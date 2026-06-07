from __future__ import annotations

from typing import Any


class DiscoveryCompatibilityMixin:
    """Legacy discovery workflow delegates for app.api.main imports."""

    api_services: Any

    async def ingest_dynamic_news_urls(
        self,
        urls: list[str],
        limit_per_query: int,
        start_date,
        end_date,
    ) -> list[dict]:
        return await self.api_services.discovery_workflow().ingest_dynamic_news_urls(
            urls,
            limit_per_query,
            start_date,
            end_date,
        )

    async def run_topic_discovery_ingestion(
        self,
        payload: Any,
        service: Any,
        plan: Any,
        limit_per_query: int,
        evidence_limit: int,
        max_queries: int,
        document_limit: int,
    ) -> dict:
        return await self.api_services.discovery_workflow().run_topic_discovery_ingestion(
            payload,
            service,
            plan,
            limit_per_query,
            evidence_limit,
            max_queries,
            document_limit,
        )

    async def discover_topic_with_timeout(self, service: Any, topic: str, timeout: int = 75) -> dict:
        return await self.api_services.discovery_workflow().discover_topic_with_timeout(
            service,
            topic,
            timeout,
        )
