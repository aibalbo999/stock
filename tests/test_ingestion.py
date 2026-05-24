import asyncio
from datetime import date

from app.data_sources.news import NewsFetcher
from app.models.schemas import ReportRequest
from app.services.ingestion import IngestionPipeline


def test_pre_report_refresh_uses_whitelist_when_tickers_empty(monkeypatch) -> None:
    pipeline = IngestionPipeline()
    calls = {}

    async def fake_ingest_feeds(enabled_sources_only: bool = True, **kwargs) -> dict:
        calls["enabled_sources_only"] = enabled_sources_only
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

    monkeypatch.setattr(pipeline, "ingest_feeds", fake_ingest_feeds)
    monkeypatch.setattr(pipeline, "refresh_market", fake_refresh_market)
    monkeypatch.setattr(pipeline, "refresh_monthly_revenue", fake_refresh_monthly_revenue)
    monkeypatch.setattr(pipeline, "refresh_financial_metrics", fake_refresh_financial_metrics)
    monkeypatch.setattr(pipeline, "refresh_valuations", fake_refresh_valuations)

    summary = asyncio.run(
        pipeline.pre_report_refresh(ReportRequest(topic="AI 產業鏈", tickers=[], lookback_days=21))
    )

    assert calls["enabled_sources_only"] is True
    assert "2330" in calls["tickers"]
    assert "2330" in calls["financial_tickers"]
    assert "2330" in calls["valuation_tickers"]
    assert calls["days"] == 21
    assert summary["news"]["count"] == 0


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

    monkeypatch.setattr(pipeline, "ingest_feeds", fake_ingest_feeds)
    monkeypatch.setattr(pipeline, "refresh_market", fake_refresh_market)
    monkeypatch.setattr(pipeline, "refresh_monthly_revenue", fake_refresh_monthly_revenue)
    monkeypatch.setattr(pipeline, "refresh_financial_metrics", fake_refresh_financial_metrics)
    monkeypatch.setattr(pipeline, "refresh_valuations", fake_refresh_valuations)

    asyncio.run(
        pipeline.pre_report_refresh(
            ReportRequest(topic="AI 產業鏈", tickers=["2330", "9999"], lookback_days=14)
        )
    )

    assert calls["tickers"] == ["2330"]
    assert calls["monthly_tickers"] == ["2330"]
    assert calls["financial_tickers"] == ["2330"]
    assert calls["valuation_tickers"] == ["2330"]


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
