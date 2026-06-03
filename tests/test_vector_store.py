import sys
from datetime import date
from types import ModuleType, SimpleNamespace

from app.core.config import get_settings
from app.data_sources.news import NewsFetcher
from app.rag.embedding_functions import GoogleGenAIEmbeddingFunction
from app.rag.timeouts import RagOperationTimeout
from app.rag.vector_store import VectorStore
from app.services.source_quality import SOURCE_CREDIBILITY_WEIGHTS


def _install_fake_chromadb(monkeypatch, fake_client_cls, embedding_functions) -> None:
    chromadb_module = ModuleType("chromadb")
    chromadb_module.PersistentClient = fake_client_cls
    utils_module = ModuleType("chromadb.utils")
    utils_module.embedding_functions = embedding_functions
    monkeypatch.setitem(sys.modules, "chromadb", chromadb_module)
    monkeypatch.setitem(sys.modules, "chromadb.utils", utils_module)


def test_fallback_search_uses_hybrid_keyword_ranking_for_ticker_and_terms(monkeypatch) -> None:
    monkeypatch.setenv("USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        store = VectorStore()
        documents = [
            NewsFetcher.from_manual_text(
                title="機器人產業概況",
                text="自動化需求成長，但沒有提到精確股票與先進封裝。",
                publisher="測試來源",
                published_at=date(2026, 5, 20),
            ),
            NewsFetcher.from_manual_text(
                title="台積電 CoWoS 先進封裝擴產",
                text="2330 台積電 CoWoS 產能擴張，AI 晶片封裝需求升溫。",
                publisher="測試來源",
                published_at=date(2026, 5, 21),
            ),
            NewsFetcher.from_manual_text(
                title="無關公司新聞",
                text="其他題材沒有股票代號也沒有 CoWoS。",
                publisher="測試來源",
                published_at=date(2026, 5, 22),
            ),
        ]

        store.upsert_documents(documents)
        results = store.search("2330 CoWoS", n_results=2)

        assert results[0].title == "台積電 CoWoS 先進封裝擴產"
        assert all(result.title != "機器人產業概況" for result in results[:1])
    finally:
        get_settings.cache_clear()


def test_tokenizer_supports_traditional_chinese_phrases() -> None:
    tokens = VectorStore._tokenize("台達電 液冷散熱 AI伺服器 CoWoS")

    assert "台達電" in tokens
    assert "液冷" in tokens
    assert "散熱" in tokens
    assert "ai伺服器" in tokens or "伺服器" in tokens
    assert "cowos" in tokens


def test_vector_store_retrieval_status_exposes_hybrid_bm25_settings() -> None:
    settings = SimpleNamespace(
        rag_hybrid_search_enabled=True,
        rag_keyword_corpus_limit=1200,
        rag_vector_weight=0.55,
        rag_keyword_weight=0.45,
        rag_rerank_top_k=24,
    )

    status = VectorStore.retrieval_runtime_status(settings)

    assert status == {
        "strategy": "hybrid-vector-bm25",
        "storage_mode": "persistent",
        "chroma_api_url_configured": False,
        "hybrid_search_enabled": True,
        "bm25_enabled": True,
        "tokenizer": "latin_terms+traditional_chinese_2_4_ngrams",
        "embedding_identity_header_enabled": True,
        "keyword_identity_fields": ["entity_tickers", "entity_names", "title", "publisher", "body"],
        "source_quality_weighting_enabled": True,
        "source_quality_weights": SOURCE_CREDIBILITY_WEIGHTS,
        "retrieval_trace_enabled": True,
        "retrieval_trace_fields": [
            "vector_score",
            "keyword_raw_score",
            "keyword_score",
            "pre_source_score",
            "source_quality_multiplier",
            "final_score",
            "reranker_status",
        ],
        "index_schema_version": "identity-v2",
        "collection_name_example": VectorStore._collection_name_for_settings(
            "ai_supply_chain_news",
            settings,
        ),
        "keyword_corpus_limit": 1200,
        "chroma_query_timeout_seconds": 0.0,
        "chroma_get_timeout_seconds": 0.0,
        "chroma_upsert_timeout_seconds": 0.0,
        "vector_weight": 0.55,
        "keyword_weight": 0.45,
        "rerank_top_k": 24,
        "reranker_timeout_seconds": 0.0,
    }


def test_vector_store_uses_chroma_http_client_when_api_url_is_configured(monkeypatch) -> None:
    captured = {}

    class FakeCollection:
        pass

    class FakeHttpClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def get_or_create_collection(self, name, **kwargs):
            captured["collection_name"] = name
            captured["collection"] = kwargs
            return FakeCollection()

    chromadb_module = ModuleType("chromadb")
    chromadb_module.HttpClient = FakeHttpClient
    chromadb_module.PersistentClient = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("PersistentClient should not be used when CHROMA_API_URL is configured")
    )
    utils_module = ModuleType("chromadb.utils")
    utils_module.embedding_functions = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "chromadb", chromadb_module)
    monkeypatch.setitem(sys.modules, "chromadb.utils", utils_module)
    monkeypatch.setenv("USE_CHROMA", "true")
    monkeypatch.setenv("CHROMA_API_URL", "https://chroma.example:8443")
    monkeypatch.setenv("CHROMA_TENANT", "stock")
    monkeypatch.setenv("CHROMA_DATABASE", "rag")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "default")
    get_settings.cache_clear()
    try:
        store = VectorStore()
    finally:
        get_settings.cache_clear()

    assert isinstance(store.collection, FakeCollection)
    assert captured["client"] == {
        "host": "chroma.example",
        "port": 8443,
        "ssl": True,
        "tenant": "stock",
        "database": "rag",
    }
    assert captured["collection_name"].startswith("ai_supply_chain_news_chroma_default")


def test_tokenizer_avoids_confusing_short_company_prefix_ngram() -> None:
    wrong_company_tokens = VectorStore._tokenize("南亞科 DRAM 記憶體供需")
    right_company_tokens = VectorStore._tokenize("南亞電子材料與工程塑膠需求")

    assert "南亞科" in wrong_company_tokens
    assert "南亞" not in wrong_company_tokens
    assert "南亞" in right_company_tokens


def test_fallback_search_does_not_treat_nanya_tech_as_nanya(monkeypatch) -> None:
    monkeypatch.setenv("USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        store = VectorStore()
        documents = [
            NewsFetcher.from_manual_text(
                title="南亞科記憶體供給吃緊",
                text="南亞科 DRAM 報價上揚，記憶體市場供需改善。",
                publisher="測試來源",
                published_at=date(2026, 5, 22),
            ),
            NewsFetcher.from_manual_text(
                title="南亞電子材料需求回升",
                text="1303 南亞工程塑膠與電子材料訂單改善。",
                publisher="測試來源",
                published_at=date(2026, 5, 20),
            ),
        ]

        store.upsert_documents(documents)
        results = store.search("南亞", n_results=2)

        assert results
        assert results[0].title == "南亞電子材料需求回升"
        assert all(result.title != "南亞科記憶體供給吃緊" for result in results[:1])
    finally:
        get_settings.cache_clear()


def test_hybrid_rank_prefers_formal_source_over_low_quality_forum(monkeypatch) -> None:
    monkeypatch.setenv("USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        store = VectorStore()
        formal = NewsFetcher.from_manual_text(
            title="富喬月營收創高 高階薄布需求升溫",
            text="1815 富喬 高階薄布 需求 成長。",
            publisher="經濟日報",
            published_at=date(2026, 5, 10),
        )
        forum = NewsFetcher.from_manual_text(
            title="1815 富喬 高階薄布 散戶閒聊-股市爆料同學會",
            text="1815 富喬 高階薄布 需求 成長，但這是散戶閒聊。",
            publisher="CMoney",
            published_at=date(2026, 5, 12),
            url="https://www.cmoney.tw/forum/stock/1815",
        )

        class IdentityReranker:
            def rerank(self, query, candidate_documents, n_results):
                return candidate_documents[:n_results]

        store.reranker = IdentityReranker()
        store.upsert_documents([forum, formal])

        results = store.search("1815 富喬 高階薄布", n_results=2)

        assert results[0].title == "富喬月營收創高 高階薄布需求升溫"
        assert VectorStore._source_quality_multiplier(formal) > VectorStore._source_quality_multiplier(forum)
    finally:
        get_settings.cache_clear()


def test_vector_store_applies_reranker_after_hybrid_candidate_collection(monkeypatch) -> None:
    monkeypatch.setenv("USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        store = VectorStore()
        documents = [
            NewsFetcher.from_manual_text(
                title="台積電 CoWoS",
                text="2330 台積電 CoWoS 產能。",
                publisher="測試來源",
                published_at=date(2026, 5, 21),
            ),
            NewsFetcher.from_manual_text(
                title="台積電 法說會",
                text="2330 台積電 法說會 提到先進封裝。",
                publisher="測試來源",
                published_at=date(2026, 5, 22),
            ),
        ]
        captured = {}

        class FakeReranker:
            def rerank(self, query, candidate_documents, n_results):
                captured["query"] = query
                captured["candidate_count"] = len(candidate_documents)
                captured["n_results"] = n_results
                return [candidate_documents[-1]]

        store.reranker = FakeReranker()
        store.upsert_documents(documents)

        results = store.search("2330 台積電", n_results=1)

        assert results[0].title == "台積電 法說會"
        assert captured == {"query": "2330 台積電", "candidate_count": 2, "n_results": 1}
    finally:
        get_settings.cache_clear()


def test_hybrid_search_records_retrieval_trace_with_score_breakdown(monkeypatch) -> None:
    monkeypatch.setenv("USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        store = VectorStore()
        formal = NewsFetcher.from_manual_text(
            title="台積電 CoWoS 先進封裝擴產",
            text="2330 台積電 CoWoS 產能擴張。",
            publisher="經濟日報",
            published_at=date(2026, 5, 20),
        )
        weaker = NewsFetcher.from_manual_text(
            title="一般 AI 伺服器新聞",
            text="伺服器需求成長。",
            publisher="測試來源",
            published_at=date(2026, 5, 21),
        )

        class IdentityReranker:
            last_status = {"execution_mode": "test_identity"}

            def rerank(self, query, candidate_documents, n_results):
                self.last_status = {"execution_mode": "test_identity", "candidate_count": len(candidate_documents)}
                return candidate_documents[:n_results]

        store.reranker = IdentityReranker()
        store.upsert_documents([weaker, formal])

        results = store.search("2330 台積電 CoWoS", n_results=1)
        trace = store.last_retrieval_trace

        assert results == [formal]
        assert trace["strategy"] == "hybrid-vector-bm25-rerank"
        assert trace["query"] == "2330 台積電 CoWoS"
        assert trace["candidate_count"] >= 1
        assert trace["returned_count"] == 1
        assert trace["result_ids"] == [formal.id]
        assert trace["reranker_status"]["execution_mode"] == "test_identity"
        first = trace["candidates"][0]
        assert first["id"] == formal.id
        assert first["keyword_raw_score"] > 0
        assert first["keyword_score"] > 0
        assert first["source_quality_multiplier"] > 0
        assert first["final_score"] == first["pre_source_score"] * first["source_quality_multiplier"]
    finally:
        get_settings.cache_clear()


def test_vector_store_target_tickers_filter_excludes_wrong_company_metadata(monkeypatch) -> None:
    monkeypatch.setenv("USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        store = VectorStore()
        wrong_company = NewsFetcher.from_manual_text(
            title="光寶科 AI 電源出貨升溫",
            text="光寶科 AI 伺服器電源需求增加。",
            publisher="測試來源",
            published_at=date(2026, 5, 22),
        ).model_copy(update={"entity_tickers": ["2301"], "entity_names": ["光寶科"]})
        right_company = NewsFetcher.from_manual_text(
            title="台達電 AI 電源出貨升溫",
            text="台達電 AI 伺服器電源與資料中心需求增加。",
            publisher="測試來源",
            published_at=date(2026, 5, 21),
        ).model_copy(update={"entity_tickers": ["2308"], "entity_names": ["台達電"]})
        legacy_unmapped = NewsFetcher.from_manual_text(
            title="AI 電源供應鏈需求升溫",
            text="AI 伺服器電源供應鏈需求增加。",
            publisher="測試來源",
            published_at=date(2026, 5, 20),
        )
        legacy_target = NewsFetcher.from_manual_text(
            title="台達電資料中心電源需求升溫",
            text="2308 台達電 AI 伺服器電源供應鏈需求增加。",
            publisher="測試來源",
            published_at=date(2026, 5, 20),
        )

        store.upsert_documents([wrong_company, right_company, legacy_unmapped, legacy_target])
        results = store.search("AI 電源", n_results=3, target_tickers=["2308"])

        assert wrong_company not in results
        assert right_company in results
        assert legacy_target in results
        assert legacy_unmapped not in results
    finally:
        get_settings.cache_clear()


def test_chroma_upsert_embeds_title_source_and_body_but_restores_body_text() -> None:
    captured = {}

    class FakeCollection:
        def upsert(self, **kwargs):
            captured.update(kwargs)

    store = object.__new__(VectorStore)
    store.collection = FakeCollection()
    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 先進封裝擴產",
        text="公司說明 AI 晶片封裝需求升溫。",
        publisher="經濟日報",
        published_at=date(2026, 5, 21),
    )

    store.upsert_documents([document])

    stored_text = captured["documents"][0]
    assert "標題：台積電 CoWoS 先進封裝擴產" in stored_text
    assert "來源：經濟日報" in stored_text
    assert "公司對應：2330 台積電" in stored_text
    assert "內文：公司說明 AI 晶片封裝需求升溫。" in stored_text
    assert captured["metadatas"][0]["entity_tickers"] == "2330"
    assert captured["metadatas"][0]["entity_names"] == "台積電"

    restored = VectorStore._document_from_metadata(
        document.id,
        stored_text,
        captured["metadatas"][0],
    )

    assert restored.title == "台積電 CoWoS 先進封裝擴產"
    assert restored.text == "公司說明 AI 晶片封裝需求升溫。"
    assert restored.entity_tickers == ["2330"]
    assert restored.entity_names == ["台積電"]


def test_upsert_documents_batches_chroma_writes_to_embedding_limit() -> None:
    calls = []

    class FakeCollection:
        def upsert(self, **kwargs):
            assert len(kwargs["ids"]) <= VectorStore.UPSERT_BATCH_SIZE
            calls.append(kwargs)

    store = object.__new__(VectorStore)
    store.collection = FakeCollection()
    documents = [
        NewsFetcher.from_manual_text(
            title=f"台積電 CoWoS 測試 {index}",
            text="2330 台積電 CoWoS 產能。",
            publisher="測試來源",
            published_at=date(2026, 5, 21),
        )
        for index in range(205)
    ]

    store.upsert_documents(documents)

    assert [len(call["ids"]) for call in calls] == [100, 100, 5]
    assert sum(len(call["documents"]) for call in calls) == 205


def test_upsert_documents_degrades_when_embedding_quota_is_exhausted() -> None:
    class FakeQuotaError(Exception):
        status_code = 429

    class FakeCollection:
        def upsert(self, **kwargs):
            raise FakeQuotaError("RESOURCE_EXHAUSTED Quota exceeded")

    store = object.__new__(VectorStore)
    store.collection = FakeCollection()
    store._fallback_docs = []
    store.last_upsert_error = None
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 測試",
            text="2330 台積電 CoWoS 產能。",
            publisher="測試來源",
            published_at=date(2026, 5, 21),
        )
    ]

    store.upsert_documents(documents)

    assert store.collection is None
    assert store._fallback_docs == documents
    assert "Quota exceeded" in store.last_upsert_error


def test_upsert_documents_degrades_when_chroma_upsert_times_out(monkeypatch) -> None:
    def fake_run_with_timeout(func, timeout_seconds, operation):
        if operation == "chroma_upsert":
            raise RagOperationTimeout("chroma_upsert timed out after 0.1s")
        return func()

    monkeypatch.setattr("app.rag.vector_store.run_with_timeout", fake_run_with_timeout)

    class FakeCollection:
        def upsert(self, **kwargs):
            raise AssertionError("timeout wrapper should stop before upsert returns")

    store = object.__new__(VectorStore)
    store.collection = FakeCollection()
    store._fallback_docs = []
    store.last_upsert_error = None
    store.settings = SimpleNamespace(rag_chroma_upsert_timeout_seconds=0.1)
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 測試",
            text="2330 台積電 CoWoS 產能。",
            publisher="測試來源",
            published_at=date(2026, 5, 21),
        )
    ]

    store.upsert_documents(documents)

    assert store.collection is None
    assert store._fallback_docs == documents
    assert "chroma_upsert timed out" in store.last_upsert_error


def test_chroma_metadata_preserves_existing_dynamic_entity_mapping() -> None:
    document = NewsFetcher.from_manual_text(
        title="奇鋐 AI 液冷散熱需求升溫",
        text="液冷散熱需求升溫。",
        publisher="測試來源",
        published_at=date(2026, 5, 21),
    ).model_copy(update={"entity_tickers": ["3017"], "entity_names": ["奇鋐"]})

    metadata = VectorStore._metadata_for_document(document)
    restored = VectorStore._document_from_metadata(
        document.id,
        VectorStore._embedding_document_text(document),
        metadata,
    )

    assert metadata["entity_tickers"] == "3017"
    assert metadata["entity_names"] == "奇鋐"
    assert restored.entity_tickers == ["3017"]
    assert restored.entity_names == ["奇鋐"]


def test_embedding_document_text_uses_existing_dynamic_entity_metadata() -> None:
    document = NewsFetcher.from_manual_text(
        title="法人說明會摘要",
        text="本季機電整合與智慧製造業務說明。",
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 21),
    ).model_copy(update={"entity_tickers": ["1504"], "entity_names": ["東元"]})

    stored_text = VectorStore._embedding_document_text(document)

    assert "公司對應：1504 東元" in stored_text
    assert "內文：本季機電整合與智慧製造業務說明。" in stored_text


def test_bm25_scores_use_entity_metadata_for_generic_company_documents() -> None:
    generic_filing = NewsFetcher.from_manual_text(
        title="法人說明會摘要",
        text="本季機電整合與智慧製造業務說明。",
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 21),
    ).model_copy(update={"entity_tickers": ["1504"], "entity_names": ["東元"]})
    unrelated = NewsFetcher.from_manual_text(
        title="法人說明會摘要",
        text="本季電源供應器與資料中心業務說明。",
        publisher="公開資訊觀測站",
        published_at=date(2026, 5, 22),
    ).model_copy(update={"entity_tickers": ["2301"], "entity_names": ["光寶科"]})

    scores = VectorStore._bm25_scores("1504 東元", [generic_filing, unrelated])

    assert scores[generic_filing.id] > 0
    assert unrelated.id not in scores


def test_fallback_search_can_find_generic_document_by_metadata_identity(monkeypatch) -> None:
    monkeypatch.setenv("USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        store = VectorStore()
        generic_filing = NewsFetcher.from_manual_text(
            title="法人說明會摘要",
            text="本季機電整合與智慧製造業務說明。",
            publisher="公開資訊觀測站",
            published_at=date(2026, 5, 21),
        ).model_copy(update={"entity_tickers": ["1504"], "entity_names": ["東元"]})
        unrelated = NewsFetcher.from_manual_text(
            title="法人說明會摘要",
            text="本季電源供應器與資料中心業務說明。",
            publisher="公開資訊觀測站",
            published_at=date(2026, 5, 22),
        ).model_copy(update={"entity_tickers": ["2301"], "entity_names": ["光寶科"]})

        store.upsert_documents([unrelated, generic_filing])
        results = store.search("1504 東元", n_results=1)

        assert results == [generic_filing]
    finally:
        get_settings.cache_clear()


def test_search_degrades_to_keyword_corpus_when_embedding_quota_is_exhausted() -> None:
    class FakeQuotaError(Exception):
        status_code = 429

    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 先進封裝擴產",
        text="2330 台積電 CoWoS 產能擴張。",
        publisher="經濟日報",
        published_at=date(2026, 5, 20),
    )
    metadata = VectorStore._metadata_for_document(document)

    class FakeCollection:
        def query(self, **kwargs):
            raise FakeQuotaError("RESOURCE_EXHAUSTED Quota exceeded")

        def get(self, **kwargs):
            return {
                "ids": [document.id],
                "documents": [VectorStore._embedding_document_text(document, metadata)],
                "metadatas": [metadata],
            }

    store = object.__new__(VectorStore)
    store.collection = FakeCollection()
    store._fallback_docs = []
    store.last_upsert_error = None
    store.last_retrieval_trace = {}

    class FakeReranker:
        last_status = {}

        def rerank(self, query, candidate_documents, n_results):
            return candidate_documents[:n_results]

    store.reranker = FakeReranker()
    store.settings = SimpleNamespace(
        rag_rerank_top_k=8,
        rag_hybrid_search_enabled=True,
        rag_keyword_corpus_limit=20,
        rag_vector_weight=0.55,
        rag_keyword_weight=0.45,
    )

    results = store.search("2330 台積電 CoWoS", n_results=1)

    assert [result.id for result in results] == [document.id]
    assert results[0].entity_tickers == ["2330"]
    assert "Quota exceeded" in store.last_upsert_error
    assert store.last_retrieval_trace["strategy"] == "hybrid-vector-bm25-rerank"


def test_search_degrades_to_keyword_corpus_when_chroma_query_times_out(monkeypatch) -> None:
    document = NewsFetcher.from_manual_text(
        title="台積電 CoWoS 先進封裝擴產",
        text="2330 台積電 CoWoS 產能擴張。",
        publisher="經濟日報",
        published_at=date(2026, 5, 20),
    )
    metadata = VectorStore._metadata_for_document(document)

    def fake_run_with_timeout(func, timeout_seconds, operation):
        if operation == "chroma_query":
            raise RagOperationTimeout("chroma_query timed out after 0.1s")
        return func()

    monkeypatch.setattr("app.rag.vector_store.run_with_timeout", fake_run_with_timeout)

    class FakeCollection:
        def query(self, **kwargs):
            raise AssertionError("query should be interrupted by timeout wrapper")

        def get(self, **kwargs):
            return {
                "ids": [document.id],
                "documents": [VectorStore._embedding_document_text(document, metadata)],
                "metadatas": [metadata],
            }

    class FakeReranker:
        last_status = {}

        def rerank(self, query, candidate_documents, n_results):
            return candidate_documents[:n_results]

    store = object.__new__(VectorStore)
    store.collection = FakeCollection()
    store._fallback_docs = []
    store.last_upsert_error = None
    store.last_retrieval_trace = {}
    store._chroma_query_disabled_for_session = False
    store._chroma_get_disabled_for_session = False
    store.reranker = FakeReranker()
    store.settings = SimpleNamespace(
        rag_rerank_top_k=8,
        rag_hybrid_search_enabled=True,
        rag_keyword_corpus_limit=20,
        rag_vector_weight=0.55,
        rag_keyword_weight=0.45,
        rag_chroma_query_timeout_seconds=0.1,
        rag_chroma_get_timeout_seconds=0.1,
    )

    results = store.search("2330 台積電 CoWoS", n_results=1)

    assert [result.id for result in results] == [document.id]
    assert "chroma_query timed out" in store.last_upsert_error
    assert store._chroma_query_disabled_for_session is True


def test_chroma_is_disabled_when_custom_embedding_unavailable_without_explicit_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeSentenceTransformerEmbeddingFunction:
        pass

    captured = {"collection_requested": False}

    class FakeClient:
        def __init__(self, path):
            captured["path"] = path

        def get_or_create_collection(self, name, **kwargs):
            captured["collection_requested"] = True
            raise AssertionError("Chroma collection should not be created when embedding fallback is disabled")

    _install_fake_chromadb(
        monkeypatch,
        FakeClient,
        SimpleNamespace(SentenceTransformerEmbeddingFunction=FakeSentenceTransformerEmbeddingFunction),
    )
    monkeypatch.setenv("USE_CHROMA", "true")
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path))
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("RAG_ALLOW_CHROMA_DEFAULT_EMBEDDING_FALLBACK", "false")
    monkeypatch.setattr("app.rag.vector_store.find_spec", lambda dependency: None)
    get_settings.cache_clear()
    try:
        store = VectorStore()

        assert store.collection is None
        assert captured["collection_requested"] is False
        assert store.embedding_status["custom_embedding_requested"] is True
        assert store.embedding_status["custom_embedding_enabled"] is False
        assert store.embedding_status["chroma_default_fallback_allowed"] is False
        assert store.embedding_status["fallback_reason"] == "missing_dependency:sentence_transformers"
    finally:
        get_settings.cache_clear()


def test_chroma_default_embedding_fallback_requires_explicit_opt_in(monkeypatch, tmp_path) -> None:
    class FakeSentenceTransformerEmbeddingFunction:
        pass

    captured = {}

    class FakeClient:
        def __init__(self, path):
            captured["path"] = path

        def get_or_create_collection(self, name, **kwargs):
            captured["name"] = name
            captured.update(kwargs)
            return "fake-collection"

    _install_fake_chromadb(
        monkeypatch,
        FakeClient,
        SimpleNamespace(SentenceTransformerEmbeddingFunction=FakeSentenceTransformerEmbeddingFunction),
    )
    monkeypatch.setenv("USE_CHROMA", "true")
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path))
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("RAG_ALLOW_CHROMA_DEFAULT_EMBEDDING_FALLBACK", "true")
    monkeypatch.setattr("app.rag.vector_store.find_spec", lambda dependency: None)
    get_settings.cache_clear()
    try:
        store = VectorStore()

        assert store.collection == "fake-collection"
        assert captured["name"].startswith("ai_supply_chain_news_chroma_default")
        assert "identity_v2" in captured["name"]
        assert len(captured["name"]) <= 63
        assert captured["embedding_function"] is None
        assert captured["metadata"]["embedding_provider"] == "chroma_default"
        assert captured["metadata"]["embedding_model"] == "chroma_default"
        assert captured["metadata"]["index_schema_version"] == "identity-v2"
        assert captured["metadata"]["document_identity_header"] == "title_source_date_company_body"
        assert store.embedding_status["chroma_default_fallback_allowed"] is True
        assert store.embedding_status["fallback_reason"] == "missing_dependency:sentence_transformers"
    finally:
        get_settings.cache_clear()


def test_chroma_is_disabled_when_embedding_factory_initialization_fails(monkeypatch, tmp_path) -> None:
    class FakeSentenceTransformerEmbeddingFunction:
        def __init__(self, **kwargs):
            raise RuntimeError("model load failed")

    captured = {"collection_requested": False}

    class FakeClient:
        def __init__(self, path):
            captured["path"] = path

        def get_or_create_collection(self, name, **kwargs):
            captured["collection_requested"] = True
            return "unexpected-collection"

    _install_fake_chromadb(
        monkeypatch,
        FakeClient,
        SimpleNamespace(SentenceTransformerEmbeddingFunction=FakeSentenceTransformerEmbeddingFunction),
    )
    monkeypatch.setenv("USE_CHROMA", "true")
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path))
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("RAG_ALLOW_CHROMA_DEFAULT_EMBEDDING_FALLBACK", "false")
    monkeypatch.setattr("app.rag.vector_store.find_spec", lambda dependency: object())
    get_settings.cache_clear()
    try:
        store = VectorStore()

        assert store.collection is None
        assert captured["collection_requested"] is False
        assert store.embedding_status["custom_embedding_enabled"] is False
        assert store.embedding_status["fallback_reason"] == "embedding_function_initialization_failed"
    finally:
        get_settings.cache_clear()


def test_chroma_collection_name_changes_with_index_schema_version() -> None:
    base_settings = SimpleNamespace(
        rag_embedding_provider="sentence_transformers",
        rag_embedding_model="intfloat/multilingual-e5-large",
        rag_index_schema_version="identity-v2",
    )
    next_settings = SimpleNamespace(
        rag_embedding_provider="sentence_transformers",
        rag_embedding_model="intfloat/multilingual-e5-large",
        rag_index_schema_version="identity-v3",
    )

    old_name = VectorStore._collection_name_for_settings("ai_supply_chain_news", base_settings)
    new_name = VectorStore._collection_name_for_settings("ai_supply_chain_news", next_settings)

    assert old_name != new_name
    assert "identity_v2" in old_name
    assert "identity_v3" in new_name
    assert len(old_name) <= 63
    assert len(new_name) <= 63


def test_chroma_collection_name_separates_default_and_custom_embedding() -> None:
    settings = SimpleNamespace(
        rag_embedding_provider="sentence_transformers",
        rag_embedding_model="intfloat/multilingual-e5-large",
        rag_index_schema_version="identity-v2",
    )

    default_name = VectorStore._collection_name_for_settings(
        "ai_supply_chain_news",
        settings,
        embedding_function_available=False,
    )
    custom_name = VectorStore._collection_name_for_settings(
        "ai_supply_chain_news",
        settings,
        embedding_function_available=True,
    )

    assert default_name != custom_name
    assert "chroma_default" in default_name
    assert "sentence_transform" in custom_name


def test_embedding_provider_status_reports_openai_ready_with_key() -> None:
    class FakeOpenAIEmbeddingFunction:
        pass

    status = VectorStore.embedding_provider_status(
        settings=SimpleNamespace(
            rag_embedding_provider="openai",
            rag_embedding_model="text-embedding-3-small",
            openai_api_key="sk-test",
            google_api_key=None,
            gemini_api_keys=[],
        ),
        embedding_functions_module=SimpleNamespace(OpenAIEmbeddingFunction=FakeOpenAIEmbeddingFunction),
        dependency_checker=lambda dependency: dependency == "openai",
    )

    assert status["custom_embedding_enabled"] is True
    assert status["factory_name"] == "OpenAIEmbeddingFunction"
    assert status["api_key_required"] is True
    assert status["api_key_configured"] is True
    assert status["fallback_reason"] is None


def test_embedding_provider_status_reports_missing_openai_key() -> None:
    class FakeOpenAIEmbeddingFunction:
        pass

    status = VectorStore.embedding_provider_status(
        settings=SimpleNamespace(
            rag_embedding_provider="openai",
            rag_embedding_model="text-embedding-3-small",
            openai_api_key=None,
            google_api_key=None,
            gemini_api_keys=[],
        ),
        embedding_functions_module=SimpleNamespace(OpenAIEmbeddingFunction=FakeOpenAIEmbeddingFunction),
        dependency_checker=lambda dependency: dependency == "openai",
    )

    assert status["custom_embedding_enabled"] is False
    assert status["fallback_reason"] == "missing_api_key"


def test_embedding_provider_status_reports_missing_google_dependency() -> None:
    class FakeGoogleEmbeddingFunction:
        pass

    status = VectorStore.embedding_provider_status(
        settings=SimpleNamespace(
            rag_embedding_provider="google",
            rag_embedding_model="text-embedding-004",
            openai_api_key=None,
            google_api_key="google-test",
            gemini_api_keys=[],
        ),
        embedding_functions_module=SimpleNamespace(
            GoogleGenerativeAiEmbeddingFunction=FakeGoogleEmbeddingFunction
        ),
        dependency_checker=lambda dependency: False,
    )

    assert status["custom_embedding_enabled"] is False
    assert status["fallback_reason"] == "missing_dependency:google.generativeai"


def test_embedding_provider_status_reports_google_genai_ready_with_key() -> None:
    status = VectorStore.embedding_provider_status(
        settings=SimpleNamespace(
            rag_embedding_provider="google_genai",
            rag_embedding_model="gemini-embedding-001",
            openai_api_key=None,
            google_api_key="google-test",
            gemini_api_keys=[],
        ),
        embedding_functions_module=SimpleNamespace(),
        dependency_checker=lambda dependency: dependency == "google.genai",
    )

    assert status["custom_embedding_enabled"] is True
    assert status["factory_name"] == "GoogleGenAIEmbeddingFunction"
    assert status["factory_available"] is True
    assert status["dependency"] == "google.genai"
    assert status["api_key_required"] is True
    assert status["api_key_configured"] is True
    assert status["fallback_reason"] is None


def test_build_embedding_function_passes_provider_specific_arguments() -> None:
    captured = {}

    class FakeGoogleEmbeddingFunction:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    settings = SimpleNamespace(
        rag_embedding_provider="google",
        rag_embedding_model="text-embedding-004",
        openai_api_key=None,
        google_api_key=None,
        gemini_api_keys=["google-key-from-list"],
    )

    embedding_function = VectorStore._build_embedding_function(
        settings,
        SimpleNamespace(GoogleGenerativeAiEmbeddingFunction=FakeGoogleEmbeddingFunction),
        dependency_checker=lambda dependency: dependency == "google.generativeai",
    )

    assert isinstance(embedding_function, FakeGoogleEmbeddingFunction)
    assert captured == {"api_key": "google-key-from-list", "model_name": "text-embedding-004"}


def test_build_embedding_function_can_use_google_genai_sdk_provider() -> None:
    settings = SimpleNamespace(
        rag_embedding_provider="google_genai",
        rag_embedding_model="gemini-embedding-001",
        rag_embedding_output_dimensionality=768,
        openai_api_key=None,
        google_api_key=None,
        gemini_api_keys=["google-key-from-list"],
    )

    embedding_function = VectorStore._build_embedding_function(
        settings,
        SimpleNamespace(),
        dependency_checker=lambda dependency: dependency == "google.genai",
    )

    assert isinstance(embedding_function, GoogleGenAIEmbeddingFunction)
    assert embedding_function.api_key == "google-key-from-list"
    assert embedding_function.model_name == "gemini-embedding-001"
    assert embedding_function.output_dimensionality == 768
    assert embedding_function.is_legacy() is False
    assert embedding_function.default_space() == "cosine"
    assert "cosine" in embedding_function.supported_spaces()
    assert embedding_function.get_config() == {
        "model_name": "gemini-embedding-001",
        "api_key_env_var": "GOOGLE_API_KEY",
        "api_key_pool_env_var": "GOOGLE_API_KEYS",
        "output_dimensionality": 768,
    }
    assert "google-key-from-list" not in str(embedding_function.get_config())


def test_google_genai_embedding_function_builds_from_env_config(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEYS", "env-pool-key,secondary")
    embedding_function = GoogleGenAIEmbeddingFunction.build_from_config(
        {
            "model_name": "gemini-embedding-001",
            "api_key_env_var": "GOOGLE_API_KEY",
            "api_key_pool_env_var": "GOOGLE_API_KEYS",
            "output_dimensionality": 768,
        }
    )

    assert embedding_function.api_key == "env-pool-key"
    assert embedding_function.model_name == "gemini-embedding-001"
    assert embedding_function.output_dimensionality == 768


def test_google_genai_embedding_function_uses_official_sdk_shape(monkeypatch) -> None:
    captured = {}

    class FakeModels:
        def embed_content(self, **kwargs):
            captured["embed_content"] = kwargs
            return SimpleNamespace(
                embeddings=[
                    SimpleNamespace(values=[0.1, 0.2]),
                    SimpleNamespace(values=[0.3, 0.4]),
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = FakeModels()

    fake_genai = SimpleNamespace(Client=FakeClient)
    fake_types = SimpleNamespace(EmbedContentConfig=lambda **kwargs: {"config": kwargs})

    def fake_import_module(name: str):
        if name == "google.genai":
            return fake_genai
        if name == "google.genai.types":
            return fake_types
        raise ImportError(name)

    monkeypatch.setattr("app.rag.embedding_functions.import_module", fake_import_module)

    embeddings = GoogleGenAIEmbeddingFunction(
        api_key="google-key",
        model_name="gemini-embedding-001",
        output_dimensionality=768,
    )(["台積電 CoWoS", "台達電 電源"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["client"] == {"api_key": "google-key"}
    assert captured["embed_content"] == {
        "model": "gemini-embedding-001",
        "contents": ["台積電 CoWoS", "台達電 電源"],
        "config": {"config": {"output_dimensionality": 768}},
    }
    assert hasattr(GoogleGenAIEmbeddingFunction, "embed_query")
    assert hasattr(GoogleGenAIEmbeddingFunction, "embed_documents")


def test_google_genai_embedding_function_batches_large_requests(monkeypatch) -> None:
    batch_lengths = []

    class FakeModels:
        def embed_content(self, **kwargs):
            contents = kwargs["contents"]
            batch_lengths.append(len(contents))
            return SimpleNamespace(
                embeddings=[SimpleNamespace(values=[float(index)]) for index, _ in enumerate(contents)]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    fake_genai = SimpleNamespace(Client=FakeClient)
    fake_types = SimpleNamespace(EmbedContentConfig=lambda **kwargs: {"config": kwargs})

    def fake_import_module(name: str):
        if name == "google.genai":
            return fake_genai
        if name == "google.genai.types":
            return fake_types
        raise ImportError(name)

    monkeypatch.setattr("app.rag.embedding_functions.import_module", fake_import_module)

    embeddings = GoogleGenAIEmbeddingFunction(
        api_key="google-key",
        model_name="gemini-embedding-001",
    )(f"文件 {index}" for index in range(101))

    assert batch_lengths == [100, 1]
    assert len(embeddings) == 101


def test_google_genai_embedding_function_retries_quota_errors(monkeypatch) -> None:
    calls = {"count": 0}
    sleeps = []

    class FakeQuotaError(Exception):
        status_code = 429

    class FakeModels:
        def embed_content(self, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise FakeQuotaError("RESOURCE_EXHAUSTED. Please retry in 4.5s.")
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.7, 0.8])])

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    fake_genai = SimpleNamespace(Client=FakeClient)
    fake_types = SimpleNamespace(EmbedContentConfig=lambda **kwargs: {"config": kwargs})

    def fake_import_module(name: str):
        if name == "google.genai":
            return fake_genai
        if name == "google.genai.types":
            return fake_types
        raise ImportError(name)

    monkeypatch.setattr("app.rag.embedding_functions.import_module", fake_import_module)
    monkeypatch.setattr("app.rag.embedding_functions.time.sleep", lambda seconds: sleeps.append(seconds))

    embeddings = GoogleGenAIEmbeddingFunction(
        api_key="google-key",
        model_name="gemini-embedding-001",
    )(["台積電 CoWoS"])

    assert embeddings == [[0.7, 0.8]]
    assert calls["count"] == 2
    assert sleeps == [4.5]
