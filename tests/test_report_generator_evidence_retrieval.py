from datetime import date

from app.data_sources.news import NewsFetcher
from app.models.schemas import ReportRequest
from app.services.llm_client import LLMResult
from app.services.report_generator import ReportGenerator
from app.services.whitelist import SupplyChainWhitelist


def test_retrieve_evidence_filters_low_quality_forum_fallback(monkeypatch) -> None:
    forum = NewsFetcher.from_manual_text(
        title="1815 富喬-追買低檔群創也不要去追高高檔的富喬住套房",
        text="散戶閒聊：追買低檔群創也不要追高高檔的富喬住套房。",
        publisher="CMoney",
        published_at=date(2026, 5, 12),
    )

    class FakeVectorStore:
        def search(self, topic: str):
            return [forum]

    def unavailable_session_scope():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.services.report_generator.session_scope", unavailable_session_scope)
    generator = ReportGenerator(vector_store=FakeVectorStore())

    documents = generator._retrieve_evidence(ReportRequest(topic="富喬 玻纖布", tickers=["1815"]))

    assert documents == []


def test_retrieve_evidence_expands_vector_queries_with_graph_neighbors(monkeypatch) -> None:
    formal_document = NewsFetcher.from_manual_text(
        title="雙鴻切入 AI 伺服器液冷供應鏈 伺服器 ODM 拉貨升溫",
        text="3324 雙鴻 AI 伺服器散熱與液冷需求提升，2382 廣達與 3231 緯創等伺服器 ODM 拉貨升溫。",
        publisher="測試財經新聞",
        published_at=date(2026, 5, 20),
    )
    queries: list[str] = []

    class FakeVectorStore:
        def search(self, topic: str):
            queries.append(topic)
            if "3324" in topic and ("2382" in topic or "廣達" in topic):
                return [formal_document]
            return []

    def unavailable_session_scope():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.services.report_generator.session_scope", unavailable_session_scope)
    generator = ReportGenerator(vector_store=FakeVectorStore())

    documents = generator._retrieve_evidence(ReportRequest(topic="AI 伺服器散熱", tickers=["3324"]))

    assert documents == [formal_document]
    assert queries[0] == "AI 伺服器散熱"
    assert any("3324" in query and ("2382" in query or "廣達" in query) for query in queries[1:])
    assert any("下游需求端" in query for query in queries[1:])


def test_generate_includes_graphrag_reasoning_context_in_llm_prompt(monkeypatch) -> None:
    document = NewsFetcher.from_manual_text(
        title="雙鴻 AI 液冷散熱需求提升",
        text="3324 雙鴻 AI 伺服器液冷散熱需求提升，2382 廣達伺服器拉貨升溫。",
        publisher="測試財經新聞",
        published_at=date(2026, 5, 20),
    )
    captured = {}

    def unavailable_session_scope():
        raise RuntimeError("database unavailable")

    def fake_generate(prompt: str, **_kwargs):
        captured["prompt"] = prompt
        return LLMResult(text='{"items":[]}', model="gemini-3.5-flash", provider="google_genai")

    monkeypatch.setattr("app.services.report_generator.session_scope", unavailable_session_scope)
    generator = ReportGenerator()
    generator.llm.generate_structured_with_metadata = fake_generate

    generator.generate(
        ReportRequest(topic="AI 伺服器散熱", tickers=["3324"]),
        documents=[document],
    )

    assert "GraphRAG 路徑推理" in captured["prompt"]
    assert "3324" in captured["prompt"]
    assert "2382" in captured["prompt"]
    assert generator.last_graph_reasoning_plan["status"] == "ready"
    assert generator.last_graph_reasoning_plan["requested_ticker_count"] == 1
    assert generator.last_graph_reasoning_plan["covered_ticker_count"] == 1
    assert generator.last_graph_reasoning_plan["missing_ticker_count"] == 0
    assert generator.last_graph_reasoning_plan["path_count"] > 0
    assert generator.last_graph_reasoning_plan["coverage_ratio"] == 1.0


def test_retrieve_evidence_passes_target_tickers_to_vector_search(monkeypatch) -> None:
    formal_document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源需求成長",
        text="2308 台達電 AI 電源需求成長。",
        publisher="測試財經新聞",
        published_at=date(2026, 5, 20),
    )
    calls = []

    class FakeVectorStore:
        def search(self, topic: str, target_tickers=None):
            calls.append({"topic": topic, "target_tickers": target_tickers})
            return [formal_document] if target_tickers == ["2308"] else []

    def unavailable_session_scope():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.services.report_generator.session_scope", unavailable_session_scope)
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與散熱",
                "status": "evidence_supported",
                "evidence_keywords": ["電源"],
            }
        ]
    )
    generator = ReportGenerator(vector_store=FakeVectorStore(), whitelist=whitelist)

    documents = generator._retrieve_evidence(ReportRequest(topic="AI 電源", tickers=["2308"]))

    assert documents == [formal_document]
    assert calls
    assert all(call["target_tickers"] == ["2308"] for call in calls)


def test_retrieve_evidence_passes_target_aliases_to_vector_search(monkeypatch) -> None:
    formal_document = NewsFetcher.from_manual_text(
        title="台達電 AI 電源需求成長",
        text="台達電 AI 電源需求成長。",
        publisher="測試財經新聞",
        published_at=date(2026, 5, 20),
    )
    calls = []

    class FakeVectorStore:
        def search(self, topic: str, target_tickers=None, target_aliases=None):
            calls.append(
                {
                    "topic": topic,
                    "target_tickers": target_tickers,
                    "target_aliases": target_aliases,
                }
            )
            return [formal_document] if target_aliases and "台達電" in target_aliases.get("2308", []) else []

    def unavailable_session_scope():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.services.report_generator.session_scope", unavailable_session_scope)
    whitelist = SupplyChainWhitelist.from_candidate_whitelist(
        [
            {
                "ticker": "2308",
                "name": "台達電",
                "segment": "電源與散熱",
                "status": "evidence_supported",
                "evidence_keywords": ["電源"],
            }
        ]
    )
    generator = ReportGenerator(vector_store=FakeVectorStore(), whitelist=whitelist)

    documents = generator._retrieve_evidence(ReportRequest(topic="AI 電源", tickers=["2308"]))

    assert documents == [formal_document]
    assert calls
    assert all(call["target_aliases"]["2308"] == ["2308", "台達電"] for call in calls)
