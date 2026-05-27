import asyncio
from contextlib import contextmanager
from datetime import date

from app.data_sources.company_filings import CompanyFilingFetcher
from app.data_sources.market import MarketDataClient
from app.data_sources.news import NewsFetcher
from app.models.schemas import MarketSnapshot, ReportRequest
from app.services.ingestion import (
    IngestionPipeline,
    classify_company_filing_error,
    company_filing_gap_summary,
    company_filing_next_actions,
    company_filing_status,
)


def test_source_category_counts_sum_stored_documents() -> None:
    assert IngestionPipeline._source_category_counts(
        [
            {"category": "cloud_capex", "stored_count": 3},
            {"category": "cloud_capex", "stored_count": 2},
            {"category": "taiwan_news", "stored_count": 4},
            {"stored_count": 1},
        ]
    ) == {"cloud_capex": 5, "taiwan_news": 4, "news": 1}


def test_pre_report_refresh_uses_whitelist_when_tickers_empty(monkeypatch) -> None:
    pipeline = IngestionPipeline()
    calls = {}

    async def fake_ingest_feeds(enabled_sources_only: bool = True, **kwargs) -> dict:
        calls["enabled_sources_only"] = enabled_sources_only
        calls.update(kwargs)
        return {"count": 0, "items": [], "errors": []}

    async def fake_refresh_market(tickers: list[str], start_date: date, end_date: date) -> dict:
        calls["tickers"] = tickers
        calls["days"] = (end_date - start_date).days
        return {"requested_tickers": tickers, "stored": []}

    async def fake_refresh_monthly_revenue(
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        calls["monthly_tickers"] = tickers
        return {"requested_tickers": tickers, "stored_count": 0}

    async def fake_refresh_financial_metrics(
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        calls["financial_tickers"] = tickers
        return {"requested_tickers": tickers, "stored_count": 0}

    async def fake_refresh_valuations(
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        calls["valuation_tickers"] = tickers
        return {"requested_tickers": tickers, "stored": []}

    async def fake_ingest_company_filings(
        tickers: list[str],
        limit_per_query: int = 3,
        filter_allowed: bool = True,
    ) -> dict:
        calls["company_filing_tickers"] = tickers
        return {"requested_tickers": tickers, "stored_count": 0}

    monkeypatch.setattr(pipeline, "ingest_feeds", fake_ingest_feeds)
    monkeypatch.setattr(pipeline, "refresh_market", fake_refresh_market)
    monkeypatch.setattr(pipeline, "refresh_monthly_revenue", fake_refresh_monthly_revenue)
    monkeypatch.setattr(pipeline, "refresh_financial_metrics", fake_refresh_financial_metrics)
    monkeypatch.setattr(pipeline, "refresh_valuations", fake_refresh_valuations)
    monkeypatch.setattr(pipeline, "ingest_company_filings", fake_ingest_company_filings)

    summary = asyncio.run(
        pipeline.pre_report_refresh(ReportRequest(topic="AI 產業鏈", tickers=[], lookback_days=21))
    )

    assert calls["enabled_sources_only"] is True
    assert calls["topic"] == "AI 產業鏈"
    assert "2330" in calls["tickers"]
    assert "2330" in calls["financial_tickers"]
    assert "2330" in calls["valuation_tickers"]
    assert "2330" in calls["company_filing_tickers"]
    assert calls["days"] == 21
    assert summary["news"]["count"] == 0
    assert "company_filings" in summary


def test_pre_report_refresh_filters_requested_tickers(monkeypatch) -> None:
    pipeline = IngestionPipeline()
    calls = {}

    async def fake_ingest_feeds(enabled_sources_only: bool = True, **kwargs) -> dict:
        return {"count": 0, "items": [], "errors": []}

    async def fake_refresh_market(tickers: list[str], start_date: date, end_date: date) -> dict:
        calls["tickers"] = tickers
        return {"requested_tickers": tickers, "stored": []}

    async def fake_refresh_monthly_revenue(
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        calls["monthly_tickers"] = tickers
        return {"requested_tickers": tickers, "stored_count": 0}

    async def fake_refresh_financial_metrics(
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        calls["financial_tickers"] = tickers
        return {"requested_tickers": tickers, "stored_count": 0}

    async def fake_refresh_valuations(
        tickers: list[str],
        start_date: date,
        end_date: date,
        filter_allowed: bool = True,
    ) -> dict:
        calls["valuation_tickers"] = tickers
        return {"requested_tickers": tickers, "stored": []}

    async def fake_ingest_company_filings(
        tickers: list[str],
        limit_per_query: int = 3,
        filter_allowed: bool = True,
    ) -> dict:
        calls["company_filing_tickers"] = tickers
        return {"requested_tickers": tickers, "stored_count": 0}

    monkeypatch.setattr(pipeline, "ingest_feeds", fake_ingest_feeds)
    monkeypatch.setattr(pipeline, "refresh_market", fake_refresh_market)
    monkeypatch.setattr(pipeline, "refresh_monthly_revenue", fake_refresh_monthly_revenue)
    monkeypatch.setattr(pipeline, "refresh_financial_metrics", fake_refresh_financial_metrics)
    monkeypatch.setattr(pipeline, "refresh_valuations", fake_refresh_valuations)
    monkeypatch.setattr(pipeline, "ingest_company_filings", fake_ingest_company_filings)

    asyncio.run(
        pipeline.pre_report_refresh(
            ReportRequest(topic="AI 產業鏈", tickers=["2330", "9999"], lookback_days=14)
        )
    )

    assert calls["tickers"] == ["2330"]
    assert calls["monthly_tickers"] == ["2330"]
    assert calls["financial_tickers"] == ["2330"]
    assert calls["valuation_tickers"] == ["2330"]
    assert calls["company_filing_tickers"] == ["2330"]


def test_refresh_market_can_keep_dynamic_ai_tickers(monkeypatch) -> None:
    pipeline = IngestionPipeline()

    async def fake_histories(self, tickers: list[str], start_date: date, end_date: date):
        return {
            ticker: [MarketSnapshot(ticker=ticker, trade_date=end_date, close=100.0)]
            for ticker in tickers
        }, []

    monkeypatch.setattr(MarketDataClient, "get_price_histories_with_errors", fake_histories)

    result = asyncio.run(
        pipeline.refresh_market(
            ["3017", "2059"],
            date(2026, 5, 1),
            date(2026, 5, 25),
            filter_allowed=False,
        )
    )

    assert result["requested_tickers"] == ["3017", "2059"]
    assert result["stored_history_count"] == 2


def test_ingest_company_filings_reports_per_ticker_gaps(monkeypatch) -> None:
    stored = {"vector_count": 0, "repository_count": 0}

    class FakeVectorStore:
        def upsert_documents(self, documents):
            stored["vector_count"] = len(documents)

    class FakeCompanyFilingRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        @staticmethod
        def to_news_document(document):
            return NewsFetcher.from_manual_text(
                title=document.title,
                text=document.text,
                publisher=document.source.publisher,
                published_at=document.source.published_at,
                url=document.source.url,
            )

        def upsert_document(self, document) -> None:
            stored["repository_count"] += 1

    @contextmanager
    def fake_session_scope():
        yield object()

    async def fake_fetch_discovery_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types=None,
    ):
        if ticker == "2330":
            return [
                CompanyFilingFetcher.from_manual_text(
                    ticker="2330",
                    company_name=company_name,
                    document_type="annual_report",
                    title="台積電 2026 年報",
                    text="台積電 年報揭露 AI/HPC 需求與風險因素。" * 8,
                    publisher="公開資訊觀測站",
                    published_at=date(2026, 5, 1),
                    url="https://mops.twse.com.tw/server-java/t57sb01?co_id=2330",
                )
            ], []
        return [], [{"source": "https://news.google.com/rss/search?q=2382", "error": "HTTP 503 timeout"}]

    async def fake_fetch_official_website_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit: int = 12,
        document_types=None,
    ):
        return [], []

    async def fake_fetch_mops_annual_report_documents(
        self,
        ticker: str,
        company_name: str = "",
        years: int = 3,
    ):
        return [], []

    async def fake_fetch_web_search_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types=None,
    ):
        return [], []

    monkeypatch.setattr("app.services.ingestion.VectorStore", FakeVectorStore)
    monkeypatch.setattr("app.services.ingestion.CompanyFilingRepository", FakeCompanyFilingRepository)
    monkeypatch.setattr("app.services.ingestion.session_scope", fake_session_scope)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_discovery_documents", fake_fetch_discovery_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_mops_annual_report_documents", fake_fetch_mops_annual_report_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_official_website_documents", fake_fetch_official_website_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_web_search_documents", fake_fetch_web_search_documents)

    result = asyncio.run(
        IngestionPipeline().ingest_company_filings(
            ["2330", "2382"],
            limit_per_query=2,
        )
    )

    by_ticker = {row["ticker"]: row for row in result["per_ticker_results"]}
    assert stored == {"vector_count": 1, "repository_count": 1}
    assert by_ticker["2330"]["status"] == "sufficient"
    assert by_ticker["2382"]["status"] == "retry_recommended"
    assert by_ticker["2382"]["missing_required_types"] == ["annual_report"]
    assert by_ticker["2382"]["error_categories"] == ["retryable_source_error"]
    assert [attempt["strategy"] for attempt in by_ticker["2382"]["attempts"]] == [
        "targeted_search",
        "retry_after_source_error",
        "broaden_official_search",
        "mops_annual_report",
        "official_company_website",
        "official_web_search",
    ]
    assert result["missing_tickers"] == ["2382"]
    assert result["gap_summary"]["retryable_tickers"] == ["2382"]
    assert result["next_actions"][0]["action"] == "retry_company_filing_search"


def test_ingest_company_filings_broadens_when_targeted_type_has_no_results(monkeypatch) -> None:
    calls = []

    class FakeVectorStore:
        def upsert_documents(self, documents):
            pass

    class FakeCompanyFilingRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        @staticmethod
        def to_news_document(document):
            return NewsFetcher.from_manual_text(title=document.title, text=document.text)

        def upsert_document(self, document) -> None:
            pass

    @contextmanager
    def fake_session_scope():
        yield object()

    async def fake_fetch_discovery_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types=None,
    ):
        calls.append({"document_types": document_types, "limit_per_query": limit_per_query})
        if document_types == ["annual_report"]:
            return [], []
        return [
            CompanyFilingFetcher.from_manual_text(
                ticker=ticker,
                company_name=company_name,
                document_type="investor_presentation",
                title="廣達 法說會",
                text="廣達 法人說明會揭露 AI 伺服器訂單與風險因素。" * 8,
            )
        ], []

    async def fake_fetch_web_search_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types=None,
    ):
        return [], []

    async def fake_fetch_official_website_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit: int = 12,
        document_types=None,
    ):
        return [], []

    async def fake_fetch_mops_annual_report_documents(
        self,
        ticker: str,
        company_name: str = "",
        years: int = 3,
    ):
        return [], []

    monkeypatch.setattr("app.services.ingestion.VectorStore", FakeVectorStore)
    monkeypatch.setattr("app.services.ingestion.CompanyFilingRepository", FakeCompanyFilingRepository)
    monkeypatch.setattr("app.services.ingestion.session_scope", fake_session_scope)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_discovery_documents", fake_fetch_discovery_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_mops_annual_report_documents", fake_fetch_mops_annual_report_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_official_website_documents", fake_fetch_official_website_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_web_search_documents", fake_fetch_web_search_documents)

    result = asyncio.run(
        IngestionPipeline().ingest_company_filings(
            ["2382"],
            limit_per_query=2,
            document_types=["annual_report"],
        )
    )

    row = result["per_ticker_results"][0]
    assert calls == [
        {"document_types": ["annual_report"], "limit_per_query": 2},
        {"document_types": None, "limit_per_query": 4},
    ]
    assert [attempt["strategy"] for attempt in row["attempts"]] == [
        "targeted_search",
        "broaden_official_search",
        "mops_annual_report",
        "official_company_website",
        "official_web_search",
    ]
    assert row["stored_count"] == 1
    assert row["status"] == "needs_manual_source"
    assert row["missing_required_types"] == ["annual_report"]


def test_ingest_company_filings_uses_web_search_when_news_discovery_is_empty(monkeypatch) -> None:
    stored = {"repository_count": 0}
    company_names = []

    class FakeVectorStore:
        def upsert_documents(self, documents):
            pass

    class FakeCompanyFilingRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        @staticmethod
        def to_news_document(document):
            return NewsFetcher.from_manual_text(title=document.title, text=document.text)

        def upsert_document(self, document) -> None:
            stored["repository_count"] += 1

    @contextmanager
    def fake_session_scope():
        yield object()

    async def fake_fetch_discovery_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types=None,
    ):
        return [], []

    async def fake_fetch_web_search_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit_per_query: int = 3,
        document_types=None,
    ):
        company_names.append(company_name)
        return [
            CompanyFilingFetcher.from_manual_text(
                ticker=ticker,
                company_name=company_name,
                document_type="annual_report",
                title="川湖 2026 年報",
                text="川湖 年報揭露 AI 伺服器導軌需求與風險因素。" * 8,
                publisher="川湖 IR",
                published_at=date(2026, 5, 1),
                url="https://example.com/2059-annual-report.pdf",
            )
        ], []

    async def fake_fetch_official_website_documents(
        self,
        ticker: str,
        company_name: str = "",
        limit: int = 12,
        document_types=None,
    ):
        return [], []

    async def fake_fetch_mops_annual_report_documents(
        self,
        ticker: str,
        company_name: str = "",
        years: int = 3,
    ):
        return [], []

    monkeypatch.setattr("app.services.ingestion.VectorStore", FakeVectorStore)
    monkeypatch.setattr("app.services.ingestion.CompanyFilingRepository", FakeCompanyFilingRepository)
    monkeypatch.setattr("app.services.ingestion.session_scope", fake_session_scope)
    monkeypatch.setattr(IngestionPipeline, "_company_name_from_cached_evidence", staticmethod(lambda ticker: "川湖"))
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_discovery_documents", fake_fetch_discovery_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_mops_annual_report_documents", fake_fetch_mops_annual_report_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_official_website_documents", fake_fetch_official_website_documents)
    monkeypatch.setattr(CompanyFilingFetcher, "fetch_web_search_documents", fake_fetch_web_search_documents)

    result = asyncio.run(
        IngestionPipeline().ingest_company_filings(
            ["2059"],
            limit_per_query=2,
            filter_allowed=False,
            document_types=["annual_report"],
        )
    )

    row = result["per_ticker_results"][0]
    assert company_names == ["川湖"]
    assert row["status"] == "sufficient"
    assert row["missing_required_types"] == []
    assert stored["repository_count"] == 1


def test_classify_company_filing_errors() -> None:
    assert classify_company_filing_error("HTTP 503 timeout") == "retryable_source_error"
    assert classify_company_filing_error("PDF 掃描圖檔，請 OCR") == "manual_text_required"
    assert classify_company_filing_error("403 forbidden") == "source_access_restricted"
    assert classify_company_filing_error("content does not mention the target company") == "content_not_usable"


def test_company_filing_gap_summary_separates_retry_and_manual_actions() -> None:
    rows = [
        {
            "ticker": "2330",
            "company_name": "台積電",
            "status": "sufficient",
            "next_step": "ok",
            "missing_required_types": [],
            "missing_recommended_types": [],
        },
        {
            "ticker": "2382",
            "company_name": "廣達",
            "status": "retry_recommended",
            "next_step": "retry",
            "missing_required_types": ["annual_report"],
            "missing_recommended_types": [],
        },
        {
            "ticker": "3324",
            "company_name": "雙鴻",
            "status": "needs_manual_source",
            "next_step": "manual",
            "missing_required_types": ["annual_report"],
            "missing_recommended_types": ["investor_presentation"],
        },
    ]

    summary = company_filing_gap_summary(rows)
    actions = company_filing_next_actions(rows)

    assert summary["status_counts"] == {
        "sufficient": 1,
        "retry_recommended": 1,
        "needs_manual_source": 1,
    }
    assert summary["retryable_tickers"] == ["2382"]
    assert summary["blocked_tickers"] == ["3324"]
    assert [action["action"] for action in actions] == [
        "retry_company_filing_search",
        "manual_company_filing_import",
    ]


def test_company_filing_status_can_request_broader_search() -> None:
    assert company_filing_status([], ["annual_report"], []) == "broader_search_recommended"


def test_ingestion_filter_removes_old_and_low_quality_political_noise() -> None:
    documents = [
        NewsFetcher.from_manual_text(
            title="台積電 CoWoS 產能吃緊",
            text="台積電 CoWoS 產能吃緊。",
            publisher="test",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="政治人物談 AI 缺電互嗆打臉",
            text="政治人物互嗆，未提及資料中心或供應鏈。",
            publisher="test",
            published_at=date(2026, 5, 20),
        ),
        NewsFetcher.from_manual_text(
            title="廣達 AI 伺服器出貨",
            text="廣達 AI 伺服器出貨成長。",
            publisher="test",
            published_at=date(2025, 12, 1),
        ),
    ]

    filtered = IngestionPipeline._filter_documents(
        documents,
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 24),
        quality_filter=True,
    )

    assert [document.title for document in filtered] == ["台積電 CoWoS 產能吃緊"]


def test_ingestion_dedupes_documents_with_same_id() -> None:
    document = NewsFetcher.from_manual_text(
        title="NVIDIA AI server supply chain",
        text="NVIDIA AI server supply chain demand grows.",
        publisher="test",
        published_at=date(2026, 5, 24),
    )

    deduped = IngestionPipeline._dedupe_documents([document, document])

    assert deduped == [document]
