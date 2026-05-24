from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.news import NewsFetcher
from app.db.models import Base
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
