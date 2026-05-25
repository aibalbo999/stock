from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.news import NewsFetcher
from app.db.models import Base, NewsArticle
from app.models.schemas import ReportRequest
from app.services.entity_mapping import EntityMapper
from app.services.persistence import NewsRepository, ReportRepository
from app.services.llm_client import LLMResult
from app.services.report_generator import ReportGenerator


def test_news_and_report_persistence_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        document = NewsFetcher.from_manual_text(
            title="CoWoS 產能滿載影響 AI 伺服器交期",
            text="台積電 CoWoS 產能滿載，HBM 供給不足，使 AI 伺服器交期延長。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        )
        matches = EntityMapper().match_document(document)
        NewsRepository(session).upsert_document(
            document,
            [match.model_dump(mode="json") for match in matches],
        )

        request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
        generator = ReportGenerator()
        generator.llm.generate_with_metadata = lambda prompt: LLMResult(
            text=(
                '{"items":[{"claim":"瓶頸在 CoWoS。","source_type":"news","source_date":"2026-05-20",'
                '"source_publisher":"測試新聞",'
                '"source_title":"CoWoS 產能滿載影響 AI 伺服器交期","source_id":""}]}'
            )
        )
        response = generator.generate(request, documents=[document])
        report = ReportRepository(session).create(request, response)
        session.commit()

        assert NewsRepository(session).latest_documents(1)[0].id == document.id
        assert ReportRepository(session).get(report.id).title == "AI 產業鏈 自動分析報告"
        assert ReportRepository(session).delete(report.id) is True
        assert ReportRepository(session).get(report.id) is None
        assert ReportRepository(session).delete(report.id) is False
    finally:
        session.close()


def test_news_repository_merges_dynamic_entity_matches() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        document = NewsFetcher.from_manual_text(
            title="奇鋐 AI 液冷散熱需求升溫",
            text="奇鋐 AI 液冷散熱需求升溫，雙鴻也受惠。",
            publisher="測試新聞",
            published_at=date(2026, 5, 20),
        )
        repository = NewsRepository(session)
        repository.upsert_document(
            document,
            [
                {
                    "ticker": "3324",
                    "name": "雙鴻",
                    "segment_id": "thermal",
                    "segment_name": "散熱",
                    "matched_alias": "雙鴻",
                }
            ],
        )
        repository.upsert_document_merging_matches(
            document,
            [
                {
                    "ticker": "3017",
                    "name": "奇鋐",
                    "segment_id": "dynamic_3017",
                    "segment_name": "液冷散熱",
                    "matched_alias": "奇鋐",
                }
            ],
        )
        session.commit()

        article = session.get(NewsArticle, document.id)
        assert '"ticker": "3324"' in article.entity_matches_json
        assert '"ticker": "3017"' in article.entity_matches_json
    finally:
        session.close()
