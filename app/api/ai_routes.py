from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import api_services_provider
from app.api.schemas import TopicDiscoveryRequest


def create_ai_router(api_services: Any | None = None) -> APIRouter:
    router = APIRouter()
    services_dependency = api_services_provider(api_services)

    @router.get("/llm/status")
    def llm_status(services: Any = Depends(services_dependency)) -> dict:
        return services.llm_api().status()

    @router.post("/llm/test")
    def llm_test(services: Any = Depends(services_dependency)) -> dict:
        return services.llm_api().healthcheck()

    @router.get("/llm/usage")
    def llm_usage(limit: int = 50, services: Any = Depends(services_dependency)) -> list[dict]:
        return services.llm_api().usage_records(limit)

    @router.get("/llm/quota")
    def llm_quota(services: Any = Depends(services_dependency)) -> dict:
        return services.llm_api().quota_summary()

    @router.post("/discovery/topic-plan")
    def discovery_topic_plan(
        payload: TopicDiscoveryRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.discovery_api().topic_plan(payload)

    @router.post("/discovery/ingest")
    async def discovery_ingest(
        payload: TopicDiscoveryRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return await services.discovery_api().ingest(payload)

    @router.post("/discovery/candidate-whitelist")
    def discovery_candidate_whitelist(
        payload: TopicDiscoveryRequest,
        services: Any = Depends(services_dependency),
    ) -> dict:
        return services.discovery_api().candidate_whitelist(payload)

    return router
