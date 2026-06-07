from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.ai_routes import create_ai_router


def test_ai_router_delegates_llm_status_and_healthcheck() -> None:
    class FakeLlmApi:
        def status(self) -> dict:
            return {"provider": "litellm", "enabled": True}

        def healthcheck(self) -> dict:
            return {"ok": True, "model": "gemini/gemini-2.5-flash"}

        def usage_records(self, limit: int = 50) -> list[dict]:
            return [{"model": "gemini-3.5-flash", "limit": limit}]

        def quota_summary(self) -> dict:
            return {"recommended_model": "gemini-3.5-flash"}

    client = _client(llm_api=FakeLlmApi())

    assert client.get("/llm/status").json() == {"provider": "litellm", "enabled": True}
    assert client.post("/llm/test").json() == {"ok": True, "model": "gemini/gemini-2.5-flash"}
    assert client.get("/llm/usage?limit=3").json() == [{"model": "gemini-3.5-flash", "limit": 3}]
    assert client.get("/llm/quota").json() == {"recommended_model": "gemini-3.5-flash"}


def test_ai_router_delegates_discovery_endpoints() -> None:
    captured = {}

    class FakeDiscoveryApi:
        def topic_plan(self, payload) -> dict:
            captured["plan_topic"] = payload.topic
            return {"plan": {"topic": payload.topic}}

        async def ingest(self, payload) -> dict:
            captured["ingest_topic"] = payload.topic
            return {"queries": ["https://news.example/rss"]}

        def candidate_whitelist(self, payload) -> dict:
            captured["whitelist_topic"] = payload.topic
            return {"candidate_whitelist": [{"ticker": "2330"}]}

    client = _client(discovery_api=FakeDiscoveryApi())

    plan_response = client.post("/discovery/topic-plan", json={"topic": "AI 產業鏈"})
    ingest_response = client.post("/discovery/ingest", json={"topic": "AI 產業鏈"})
    whitelist_response = client.post("/discovery/candidate-whitelist", json={"topic": "AI 產業鏈"})

    assert plan_response.status_code == 200
    assert plan_response.json() == {"plan": {"topic": "AI 產業鏈"}}
    assert ingest_response.json() == {"queries": ["https://news.example/rss"]}
    assert whitelist_response.json() == {"candidate_whitelist": [{"ticker": "2330"}]}
    assert captured == {
        "plan_topic": "AI 產業鏈",
        "ingest_topic": "AI 產業鏈",
        "whitelist_topic": "AI 產業鏈",
    }


def _client(llm_api=None, discovery_api=None) -> TestClient:
    class FakeServices:
        def llm_api(self):
            return llm_api

        def discovery_api(self):
            return discovery_api

    app = FastAPI()
    app.include_router(create_ai_router(FakeServices()))
    return TestClient(app)
