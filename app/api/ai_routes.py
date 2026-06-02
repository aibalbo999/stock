from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.schemas import TopicDiscoveryRequest


def create_ai_router(api_services: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/llm/status")
    def llm_status() -> dict:
        return api_services.llm_api().status()

    @router.post("/llm/test")
    def llm_test() -> dict:
        return api_services.llm_api().healthcheck()

    @router.post("/discovery/topic-plan")
    def discovery_topic_plan(payload: TopicDiscoveryRequest) -> dict:
        return api_services.discovery_api().topic_plan(payload)

    @router.post("/discovery/ingest")
    async def discovery_ingest(payload: TopicDiscoveryRequest) -> dict:
        return await api_services.discovery_api().ingest(payload)

    @router.post("/discovery/candidate-whitelist")
    def discovery_candidate_whitelist(payload: TopicDiscoveryRequest) -> dict:
        return api_services.discovery_api().candidate_whitelist(payload)

    return router
