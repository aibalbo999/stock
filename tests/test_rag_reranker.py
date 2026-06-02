from datetime import date
from types import SimpleNamespace

from app.data_sources.news import NewsFetcher
from app.rag.reranker import RagReranker
from app.rag.timeouts import RagOperationTimeout


def test_keyword_reranker_preserves_hybrid_order_when_query_has_no_matches() -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "第一篇", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "第二篇", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    result = RagReranker(provider="keyword").rerank("AI", documents, n_results=1)

    assert [document.title for document in result] == ["A"]


def test_keyword_reranker_promotes_exact_ticker_company_and_topic_terms() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            "一般 AI 伺服器新聞",
            "伺服器需求成長，但沒有提到台積電或 CoWoS。",
            publisher="測試",
            published_at=date(2026, 5, 22),
        ),
        NewsFetcher.from_manual_text(
            "台積電 CoWoS 先進封裝擴產",
            "2330 台積電 CoWoS 產能擴張，AI 晶片封裝需求升溫。",
            publisher="經濟日報",
            published_at=date(2026, 5, 20),
        ),
    ]

    result = RagReranker(provider="keyword").rerank("2330 台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result] == ["台積電 CoWoS 先進封裝擴產", "一般 AI 伺服器新聞"]


def test_keyword_reranker_does_not_treat_nanya_tech_as_nanya() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            "南亞科記憶體供需升溫",
            "南亞科 DRAM 產能吃緊，記憶體報價上揚。",
            publisher="測試",
            published_at=date(2026, 5, 22),
        ),
        NewsFetcher.from_manual_text(
            "南亞電子材料訂單改善",
            "1303 南亞工程塑膠與電子材料需求回升。",
            publisher="測試",
            published_at=date(2026, 5, 20),
        ),
    ]

    result = RagReranker(provider="keyword").rerank("南亞", documents, n_results=2)

    assert [document.title for document in result][0] == "南亞電子材料訂單改善"


def test_keyword_reranker_demotes_low_quality_investor_forum_sources() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            "1815 富喬-追買低檔群創也不要去追高高檔的富喬住套房-股市爆料同學會",
            "1815 富喬 高階薄布 玻纖布 需求，但這是散戶閒聊。",
            publisher="CMoney",
            published_at=date(2026, 5, 23),
            url="https://www.cmoney.tw/forum/article/1815",
        ),
        NewsFetcher.from_manual_text(
            "富喬高階薄布接單升溫",
            "1815 富喬 高階薄布與玻纖布出貨動能改善，公司營運展望轉佳。",
            publisher="工商時報",
            published_at=date(2026, 5, 20),
        ),
    ]

    result = RagReranker(provider="keyword").rerank("1815 富喬 高階薄布", documents, n_results=2)

    assert [document.title for document in result][0] == "富喬高階薄布接單升溫"


def test_keyword_reranker_status_explains_keyword_mode() -> None:
    reranker = RagReranker(provider="keyword", model_name="unused")

    status = reranker.status()

    assert status["available"] is True
    assert status["execution_mode"] == "keyword"
    assert status["quality_tier"] == "lexical_fallback"
    assert status["keyword_fallback"] is True
    assert status["model_reranker_ready"] is False
    assert status["model_reranker_gap"] == "keyword_provider_selected"
    assert status["model_checked"] is False
    assert status["fallback_reason"] is None


def test_auto_reranker_prefers_cross_encoder_model_when_available() -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "一般 AI 伺服器新聞", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "2330 台積電 CoWoS 先進封裝", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    class FakeCrossEncoder:
        def predict(self, pairs):
            return [0.1, 0.9]

    reranker = RagReranker(
        provider="auto",
        model_name="fake-bge",
        cross_encoder_factory=lambda model_name: FakeCrossEncoder(),
    )

    result = reranker.rerank("台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result] == ["B", "A"]
    assert reranker.last_status["normalized_provider"] == "auto"
    assert reranker.last_status["resolved_provider"] == "bge"
    assert reranker.last_status["execution_mode"] == "cross_encoder"
    assert reranker.last_status["model_reranker_ready"] is True
    assert reranker.last_status["keyword_fallback"] is False


def test_auto_reranker_uses_cohere_when_local_model_is_unavailable(monkeypatch) -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "一般 AI 伺服器新聞", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "2330 台積電 CoWoS 先進封裝", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    class FakeCohereClient:
        def rerank(self, **kwargs):
            assert kwargs["model"] == "rerank-v3.5"
            return SimpleNamespace(results=[SimpleNamespace(index=1), SimpleNamespace(index=0)])

    monkeypatch.setattr("app.rag.reranker.find_spec", lambda module_name: None)
    reranker = RagReranker(
        provider="auto",
        model_name="BAAI/bge-reranker-v2-m3",
        cohere_api_key="cohere-key",
        cohere_client_factory=lambda api_key: FakeCohereClient(),
    )

    result = reranker.rerank("台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result] == ["B", "A"]
    assert reranker.last_status["normalized_provider"] == "auto"
    assert reranker.last_status["resolved_provider"] == "cohere"
    assert reranker.last_status["execution_mode"] == "cohere_api"
    assert reranker.last_status["model"] == "rerank-v3.5"
    assert reranker.last_status["model_reranker_ready"] is True


def test_auto_reranker_uses_llm_when_bge_and_cohere_are_unavailable(monkeypatch) -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "一般 AI 伺服器新聞", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "2330 台積電 CoWoS 先進封裝", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    class FakeLLMClient:
        def generate_with_metadata(self, prompt: str):
            assert "只輸出 JSON 陣列" in prompt
            assert '"index": 0, "title": "B"' in prompt
            return SimpleNamespace(text="[0, 1]", fallback=False, model="gemini-rerank", attempts=({"outcome": "success"},))

    monkeypatch.setattr("app.rag.reranker.find_spec", lambda module_name: None)
    reranker = RagReranker(
        provider="auto",
        model_name="BAAI/bge-reranker-v2-m3",
        llm_client_factory=lambda: FakeLLMClient(),
    )

    result = reranker.rerank("台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result] == ["B", "A"]
    assert reranker.last_status["normalized_provider"] == "auto"
    assert reranker.last_status["resolved_provider"] == "llm"
    assert reranker.last_status["execution_mode"] == "llm_rerank"
    assert reranker.last_status["model"] == "gemini-rerank"
    assert reranker.last_status["model_reranker_ready"] is True
    assert reranker.last_status["llm_attempt_count"] == 1


def test_auto_reranker_falls_back_to_keyword_when_llm_response_is_unparseable(monkeypatch) -> None:
    documents = [
        NewsFetcher.from_manual_text(
            "台積電 CoWoS 先進封裝擴產",
            "2330 台積電 CoWoS 產能擴張。",
            publisher="經濟日報",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text("一般 AI 伺服器新聞", "伺服器需求成長。", publisher="測試", published_at=date(2026, 5, 22)),
    ]

    calls = {"count": 0}

    class BadLLMClient:
        def generate_with_metadata(self, prompt: str):
            calls["count"] += 1
            return SimpleNamespace(text="not json", fallback=False, model="gemini-rerank", attempts=())

    monkeypatch.setattr("app.rag.reranker.find_spec", lambda module_name: None)
    reranker = RagReranker(
        provider="auto",
        model_name="BAAI/bge-reranker-v2-m3",
        llm_client_factory=lambda: BadLLMClient(),
    )

    result = reranker.rerank("2330 台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result][0] == "台積電 CoWoS 先進封裝擴產"
    assert reranker.last_status["resolved_provider"] == "keyword"
    assert reranker.last_status["keyword_fallback"] is True
    assert "prediction_failed:RuntimeError" in reranker.last_status["model_reranker_gap"]

    reranker.rerank("AI 伺服器", documents, n_results=1)

    assert calls["count"] == 1
    assert reranker.last_status["resolved_provider"] == "keyword"


def test_llm_reranker_times_out_and_falls_back_to_keyword(monkeypatch) -> None:
    documents = [
        NewsFetcher.from_manual_text(
            "台積電 CoWoS 先進封裝擴產",
            "2330 台積電 CoWoS 產能擴張。",
            publisher="經濟日報",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text("一般 AI 伺服器新聞", "伺服器需求成長。", publisher="測試", published_at=date(2026, 5, 22)),
    ]

    class SlowLLMClient:
        def generate_with_metadata(self, prompt: str):
            raise AssertionError("timeout wrapper should stop before LLM returns")

    def fake_run_with_timeout(func, timeout_seconds, operation):
        if operation == "llm_rerank":
            raise RagOperationTimeout("llm_rerank timed out after 0.1s")
        return func()

    monkeypatch.setattr("app.rag.reranker.run_with_timeout", fake_run_with_timeout)

    reranker = RagReranker(
        provider="llm",
        llm_client_factory=lambda: SlowLLMClient(),
    )

    result = reranker.rerank("2330 台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result][0] == "台積電 CoWoS 先進封裝擴產"
    assert reranker.last_status["model_reranker_ready"] is False
    assert reranker.last_status["fallback_reason"] == "timeout:llm_rerank"
    assert reranker.last_status["timeout_seconds"] == 15.0


def test_cross_encoder_model_load_timeout_falls_back_without_blocking(monkeypatch) -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "第一篇", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "第二篇", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    def fake_run_with_timeout(func, timeout_seconds, operation):
        if operation == "cross_encoder_model_load":
            raise RagOperationTimeout("cross_encoder_model_load timed out after 0.1s")
        return func()

    monkeypatch.setattr("app.rag.reranker.run_with_timeout", fake_run_with_timeout)

    reranker = RagReranker(
        provider="bge",
        model_name="fake-bge",
        cross_encoder_factory=lambda model_name: object(),
    )

    result = reranker.rerank("AI", documents, n_results=2)

    assert [document.title for document in result] == ["A", "B"]
    assert reranker.last_status["model_reranker_ready"] is False
    assert reranker.last_status["fallback_reason"] == "timeout:cross_encoder_model_load"


def test_auto_reranker_falls_back_to_keyword_and_reports_model_gaps(monkeypatch) -> None:
    documents = [
        NewsFetcher.from_manual_text(
            "台積電 CoWoS 先進封裝擴產",
            "2330 台積電 CoWoS 產能擴張。",
            publisher="經濟日報",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text("一般 AI 伺服器新聞", "伺服器需求成長。", publisher="測試", published_at=date(2026, 5, 22)),
    ]

    monkeypatch.setattr("app.rag.reranker.find_spec", lambda module_name: None)
    reranker = RagReranker(
        provider="auto",
        model_name="BAAI/bge-reranker-v2-m3",
        llm_reranker_enabled=False,
    )

    result = reranker.rerank("2330 台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result][0] == "台積電 CoWoS 先進封裝擴產"
    assert reranker.last_status["normalized_provider"] == "auto"
    assert reranker.last_status["resolved_provider"] == "keyword"
    assert reranker.last_status["execution_mode"] == "keyword"
    assert reranker.last_status["keyword_fallback"] is True
    assert reranker.last_status["model_reranker_ready"] is False
    assert "missing_dependency:sentence_transformers" in reranker.last_status["model_reranker_gap"]
    assert "missing_api_key" in reranker.last_status["model_reranker_gap"]
    assert "llm_reranker_disabled" in reranker.last_status["model_reranker_gap"]


def test_cross_encoder_status_reports_missing_dependency(monkeypatch) -> None:
    monkeypatch.setattr("app.rag.reranker.find_spec", lambda module_name: None)
    reranker = RagReranker(provider="bge", model_name="BAAI/bge-reranker-v2-m3")

    status = reranker.status()

    assert status["available"] is False
    assert status["execution_mode"] == "input_order_fallback"
    assert status["dependency"] == "sentence_transformers"
    assert status["dependency_available"] is False
    assert status["model_available"] is False
    assert status["fallback_reason"] == "missing_dependency:sentence_transformers"


def test_cross_encoder_reranker_sorts_by_model_scores() -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "一般 AI 伺服器新聞", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "2330 台積電 CoWoS 先進封裝", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    class FakeCrossEncoder:
        def predict(self, pairs):
            assert pairs[0][0] == "台積電 CoWoS"
            assert "一般 AI 伺服器新聞" in pairs[0][1]
            assert "2330 台積電 CoWoS" in pairs[1][1]
            return [0.1, 0.9]

    reranker = RagReranker(
        provider="sentence_transformers",
        model_name="fake-bge",
        cross_encoder_factory=lambda model_name: FakeCrossEncoder(),
    )

    result = reranker.rerank("台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result] == ["B", "A"]
    assert reranker.available() is True
    assert reranker.last_status["execution_mode"] == "cross_encoder"
    assert reranker.last_status["model_reranker_ready"] is True
    assert reranker.last_status["quality_tier"] == "model_reranker"
    assert reranker.last_status["fallback_reason"] is None


def test_cross_encoder_reranker_falls_back_when_model_fails() -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "第一篇", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "第二篇", publisher="測試", published_at=date(2026, 5, 2)),
    ]
    reranker = RagReranker(
        provider="sentence_transformers",
        model_name="fake-bge",
        cross_encoder_factory=lambda model_name: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = reranker.rerank("AI", documents, n_results=2)

    assert [document.title for document in result] == ["A", "B"]
    assert reranker.available() is False
    assert reranker.last_status["execution_mode"] == "input_order_fallback"
    assert reranker.last_status["model_reranker_ready"] is False
    assert reranker.last_status["model_reranker_gap"] == "model_unavailable"
    assert reranker.last_status["fallback_reason"] == "model_unavailable"


def test_cross_encoder_reranker_records_prediction_failure() -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "第一篇", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "第二篇", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    class FakeCrossEncoder:
        def predict(self, pairs):
            raise RuntimeError("boom")

    reranker = RagReranker(
        provider="bge",
        model_name="fake-bge",
        cross_encoder_factory=lambda model_name: FakeCrossEncoder(),
    )

    result = reranker.rerank("AI", documents, n_results=2)

    assert [document.title for document in result] == ["A", "B"]
    assert reranker.last_status["available"] is False
    assert reranker.last_status["model_available"] is True
    assert reranker.last_status["fallback_reason"] == "prediction_failed:RuntimeError"


def test_reranker_truncates_long_document_text_before_prediction() -> None:
    document = NewsFetcher.from_manual_text(
        "長文",
        "A" * 100,
        publisher="測試",
        published_at=date(2026, 5, 1),
    )
    captured = {}

    class FakeCrossEncoder:
        def predict(self, pairs):
            captured["document_text"] = pairs[0][1]
            return [1.0]

    reranker = RagReranker(
        provider="bge",
        model_name="fake-bge",
        text_limit=10,
        cross_encoder_factory=lambda model_name: FakeCrossEncoder(),
    )

    reranker.rerank("AI", [document], n_results=1)

    assert len(captured["document_text"]) == 10


def test_cohere_reranker_sorts_by_api_result_indexes() -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "一般 AI 伺服器新聞", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "2330 台積電 CoWoS 先進封裝", publisher="測試", published_at=date(2026, 5, 2)),
    ]
    captured = {}

    class FakeCohereClient:
        def rerank(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(results=[SimpleNamespace(index=1), SimpleNamespace(index=0)])

    reranker = RagReranker(
        provider="cohere",
        model_name="rerank-v3.5",
        cohere_api_key="test-key",
        cohere_client_factory=lambda api_key: FakeCohereClient(),
    )

    result = reranker.rerank("台積電 CoWoS", documents, n_results=2)

    assert [document.title for document in result] == ["B", "A"]
    assert captured["model"] == "rerank-v3.5"
    assert captured["query"] == "台積電 CoWoS"
    assert captured["top_n"] == 2
    assert "2330 台積電 CoWoS" in captured["documents"][1]
    assert reranker.available() is True
    assert reranker.last_status["execution_mode"] == "cohere_api"
    assert reranker.last_status["model_reranker_ready"] is True
    assert reranker.last_status["quality_tier"] == "api_model_reranker"
    assert reranker.last_status["api_key_configured"] is True


def test_cohere_reranker_status_reports_missing_key_before_api_call() -> None:
    reranker = RagReranker(
        provider="cohere",
        model_name="rerank-v3.5",
        cohere_api_key="",
        cohere_client_factory=lambda api_key: (_ for _ in ()).throw(AssertionError("should not build client")),
    )

    status = reranker.status()

    assert status["available"] is False
    assert status["execution_mode"] == "input_order_fallback"
    assert status["dependency"] == "cohere"
    assert status["dependency_available"] is True
    assert status["api_key_required"] is True
    assert status["api_key_configured"] is False
    assert status["fallback_reason"] == "missing_api_key"


def test_cohere_reranker_falls_back_when_api_prediction_fails() -> None:
    documents = [
        NewsFetcher.from_manual_text("A", "第一篇", publisher="測試", published_at=date(2026, 5, 1)),
        NewsFetcher.from_manual_text("B", "第二篇", publisher="測試", published_at=date(2026, 5, 2)),
    ]

    class FakeCohereClient:
        def rerank(self, **kwargs):
            raise RuntimeError("boom")

    reranker = RagReranker(
        provider="cohere_rerank",
        model_name="rerank-v3.5",
        cohere_api_key="test-key",
        cohere_client_factory=lambda api_key: FakeCohereClient(),
    )

    result = reranker.rerank("AI", documents, n_results=2)

    assert [document.title for document in result] == ["A", "B"]
    assert reranker.last_status["available"] is False
    assert reranker.last_status["execution_mode"] == "input_order_fallback"
    assert reranker.last_status["model_available"] is True
    assert reranker.last_status["fallback_reason"] == "prediction_failed:RuntimeError"
