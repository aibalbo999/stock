import json
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_sources.news import NewsFetcher
from app.db.models import Base, GeneratedReport, NewsArticle
from app.models.schemas import ReportRequest, ReportResponse, RiskFinding, RiskType, Source
from app.services.entity_mapping import EntityMapper
from app.services.persistence import (
    AnalysisRunRepository,
    LLMUsageRepository,
    NewsRepository,
    ReportRepository,
)
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
        if response.quality_gate:
            assert json.loads(ReportRepository(session).get(report.id).quality_gate_json) == response.quality_gate
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
        restored = repository.latest_documents(1)[0]
        assert restored.entity_tickers == ["3324", "3017"]
        assert restored.entity_names == ["雙鴻", "奇鋐"]
    finally:
        session.close()


def test_report_repository_sanitizes_non_formal_sources_before_persisting() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        request = ReportRequest(topic="AI 產業鏈", tickers=["1815"])
        response = ReportResponse(
            title="AI 產業鏈 自動分析報告",
            markdown="\n".join(
                [
                    "# AI 產業鏈 自動分析報告",
                    "- 2026-05-08 CMoney投資網誌《富喬還能追嗎》",
                    "- 2026-05-09 經濟日報《富喬月營收創高》",
                    "| 股票 | 代表來源 |",
                    "|---|---|",
                    "| 1815 富喬 | 2026-05-08 CMoney投資網誌《富喬還能追嗎》；2026-05-09 經濟日報《富喬月營收創高》 |",
                ]
            ),
        )

        report = ReportRepository(session).create(request, response)
        session.commit()

        stored = ReportRepository(session).get(report.id)
        assert stored is not None
        assert "CMoney投資網誌" not in stored.markdown
        assert "經濟日報《富喬月營收創高》" in stored.markdown
    finally:
        session.close()


def test_report_repository_persists_structured_quality_gate_payload() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        request = ReportRequest(topic="AI 產業鏈", tickers=["2330"])
        response = ReportResponse(
            title="AI 產業鏈 自動分析報告",
            markdown="# AI 產業鏈 自動分析報告",
            quality_gate={
                "status": "ready",
                "warnings": [],
                "metrics": {"promoted_count": 1, "market_coverage": 1.0},
            },
        )

        report = ReportRepository(session).create(request, response)
        session.commit()

        stored = ReportRepository(session).get(report.id)
        assert stored is not None
        assert json.loads(stored.quality_gate_json) == response.quality_gate
    finally:
        session.close()


def test_report_repository_keeps_only_latest_report_per_topic() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = ReportRepository(session)
        old_report = repository.create(
            ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            ReportResponse(title="old", markdown="# old"),
        )
        other_topic_report = repository.create(
            ReportRequest(topic="機器人 產業鏈", tickers=["2359"]),
            ReportResponse(title="robot", markdown="# robot"),
        )
        run = AnalysisRunRepository(session).start("test", {})
        AnalysisRunRepository(session).mark_success(
            run.id,
            old_report.id,
            "reports/20260606_120000_AI.md",
        )

        latest_report = repository.create(
            ReportRequest(topic="AI 產業鏈", tickers=["3324"]),
            ReportResponse(title="new", markdown="# new"),
        )
        retention = repository.last_retention_result
        session.commit()

        assert repository.get(old_report.id) is None
        assert repository.get(latest_report.id) is not None
        assert repository.get(other_topic_report.id) is not None
        assert retention == {
            "policy": "latest_per_topic",
            "topic": "AI 產業鏈",
            "report_id": latest_report.id,
            "old_report_versions_deleted": 1,
            "old_report_ids": [old_report.id],
            "run_links_cleared": True,
            "run_output_paths_cleared": True,
        }
        restored_run = AnalysisRunRepository(session).get(run.id)
        assert restored_run.report_id is None
        assert restored_run.output_path is None
    finally:
        session.close()


def test_report_repository_delete_clears_analysis_run_link_and_output_path() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        report_repository = ReportRepository(session)
        run_repository = AnalysisRunRepository(session)
        report = report_repository.create(
            ReportRequest(topic="AI 產業鏈", tickers=["2330"]),
            ReportResponse(title="AI report", markdown="# report"),
        )
        run = run_repository.start("test", {})
        run_repository.mark_success(run.id, report.id, "reports/20260607_080000_AI.md")
        session.commit()

        assert run_repository.output_paths_for_report(report.id) == ["reports/20260607_080000_AI.md"]
        assert report_repository.delete(report.id) is True
        session.commit()

        restored_run = run_repository.get(run.id)
        assert restored_run.report_id is None
        assert restored_run.output_path is None
    finally:
        session.close()


def test_report_repository_delete_before_clears_analysis_run_link_and_output_path() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        old_report = GeneratedReport(
            title="old ai",
            topic="AI",
            tickers_json="[]",
            findings_json="[]",
            markdown="# old",
            generated_at=datetime(2026, 5, 1, 9, 0, 0),
        )
        latest_report = GeneratedReport(
            title="new ai",
            topic="AI",
            tickers_json="[]",
            findings_json="[]",
            markdown="# new",
            generated_at=datetime(2026, 5, 2, 9, 0, 0),
        )
        session.add_all([old_report, latest_report])
        session.flush()
        run_repository = AnalysisRunRepository(session)
        run = run_repository.start("legacy", {})
        run_repository.mark_success(
            run.id,
            old_report.id,
            "reports/20260501_090000_AI.md",
        )
        session.commit()

        assert ReportRepository(session).delete_before(datetime(2026, 5, 2, 0, 0, 0)) == 1
        session.commit()

        restored_run = run_repository.get(run.id)
        assert session.get(GeneratedReport, old_report.id) is None
        assert session.get(GeneratedReport, latest_report.id) is not None
        assert restored_run.report_id is None
        assert restored_run.output_path is None
    finally:
        session.close()


def test_report_repository_lists_latest_report_per_topic_for_legacy_duplicates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        session.add_all(
            [
                GeneratedReport(
                    title="old ai",
                    topic="AI",
                    tickers_json="[]",
                    findings_json="[]",
                    markdown="# old",
                    generated_at=datetime(2026, 5, 1, 9, 0, 0),
                ),
                GeneratedReport(
                    title="new ai",
                    topic="AI",
                    tickers_json="[]",
                    findings_json="[]",
                    markdown="# new",
                    generated_at=datetime(2026, 5, 2, 9, 0, 0),
                ),
                GeneratedReport(
                    title="robot",
                    topic="Robot",
                    tickers_json="[]",
                    findings_json="[]",
                    markdown="# robot",
                    generated_at=datetime(2026, 5, 3, 9, 0, 0),
                ),
            ]
        )
        session.commit()

        reports = ReportRepository(session).latest_by_topic(20)

        assert [report.title for report in reports] == ["robot", "new ai"]
    finally:
        session.close()


def test_report_repository_latest_by_topic_breaks_timestamp_ties_by_newer_id() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        same_generated_at = datetime(2026, 5, 2, 9, 0, 0)
        session.add_all(
            [
                GeneratedReport(
                    title="old ai",
                    topic="AI",
                    tickers_json="[]",
                    findings_json="[]",
                    markdown="# old",
                    generated_at=same_generated_at,
                ),
                GeneratedReport(
                    title="new ai",
                    topic="AI",
                    tickers_json="[]",
                    findings_json="[]",
                    markdown="# new",
                    generated_at=same_generated_at,
                ),
                GeneratedReport(
                    title="robot",
                    topic="Robot",
                    tickers_json="[]",
                    findings_json="[]",
                    markdown="# robot",
                    generated_at=datetime(2026, 5, 1, 9, 0, 0),
                ),
            ]
        )
        session.commit()

        repository = ReportRepository(session)

        assert repository.latest(1)[0].title == "new ai"
        assert [report.title for report in repository.latest_by_topic(20)] == ["new ai", "robot"]
    finally:
        session.close()


def test_report_repository_prunes_legacy_duplicate_topic_reports_and_run_links() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        old_ai = GeneratedReport(
            title="old ai",
            topic="AI",
            tickers_json="[]",
            findings_json="[]",
            markdown="# old",
            generated_at=datetime(2026, 5, 1, 9, 0, 0),
        )
        new_ai = GeneratedReport(
            title="new ai",
            topic="AI",
            tickers_json="[]",
            findings_json="[]",
            markdown="# new",
            generated_at=datetime(2026, 5, 2, 9, 0, 0),
        )
        robot = GeneratedReport(
            title="robot",
            topic="Robot",
            tickers_json="[]",
            findings_json="[]",
            markdown="# robot",
            generated_at=datetime(2026, 5, 3, 9, 0, 0),
        )
        session.add_all([old_ai, new_ai, robot])
        session.flush()
        run = AnalysisRunRepository(session).start("legacy", {})
        AnalysisRunRepository(session).mark_success(
            run.id,
            report_id=old_ai.id,
            output_path="reports/20260501_090000_AI.md",
        )
        session.commit()

        assert ReportRepository(session).prune_older_by_topic() == 1
        session.commit()

        assert session.get(GeneratedReport, old_ai.id) is None
        assert session.get(GeneratedReport, new_ai.id) is not None
        assert session.get(GeneratedReport, robot.id) is not None
        restored_run = AnalysisRunRepository(session).get(run.id)
        assert restored_run.report_id is None
        assert restored_run.output_path is None
    finally:
        session.close()


def test_analysis_run_repository_clear_orphan_report_refs_clears_output_path() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        run_repository = AnalysisRunRepository(session)
        run = run_repository.start("legacy", {})
        run_repository.mark_success(run.id, 999, "reports/missing.md")
        session.commit()

        assert run_repository.orphan_report_ids() == [run.id]
        assert run_repository.clear_orphan_report_refs() == 1
        session.commit()

        restored_run = run_repository.get(run.id)
        assert restored_run.report_id is None
        assert restored_run.output_path is None
    finally:
        session.close()


def test_report_repository_sanitizes_non_formal_findings_before_persisting() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        request = ReportRequest(topic="AI 產業鏈", tickers=["1815", "2330"])
        response = ReportResponse(
            title="AI 產業鏈 自動分析報告",
            markdown="# AI 產業鏈 自動分析報告\n\n正式來源檢查通過。",
            findings=[
                RiskFinding(
                    risk_type=RiskType.opportunity_or_growth,
                    topic="散戶熱度",
                    evidence="追買低檔群創也不要去追高高檔的富喬住套房",
                    source=Source(
                        title="1815 富喬-股市爆料同學會",
                        publisher="CMoney",
                        url="https://www.cmoney.tw/forum/stock/1815",
                        published_at=date(2026, 5, 12),
                    ),
                ),
                RiskFinding(
                    risk_type=RiskType.structural_bottleneck,
                    topic="CoWoS",
                    evidence="台積電 CoWoS 產能吃緊",
                    source=Source(
                        title="台積電 CoWoS 產能吃緊",
                        publisher="經濟日報",
                        published_at=date(2026, 5, 13),
                    ),
                ),
            ],
        )

        report = ReportRepository(session).create(request, response)
        session.commit()

        stored = ReportRepository(session).get(report.id)
        assert stored is not None
        persisted_findings = json.loads(stored.findings_json)
        assert len(persisted_findings) == 1
        assert persisted_findings[0]["source"]["publisher"] == "經濟日報"
        assert "股市爆料同學會" not in stored.findings_json
    finally:
        session.close()


def test_llm_usage_repository_records_report_execution_summary() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        record = LLMUsageRepository(session).create_from_report_execution(
            operation="report_generation",
            report_id=12,
            run_id=34,
            report_execution={
                "llm": {
                    "fallback": False,
                    "model": "gemini-3.5-flash",
                    "provider": "google_genai",
                    "observability": {
                        "latency_ms": 123.4,
                        "input_token_estimate": 1000,
                        "output_token_estimate": 250,
                        "total_token_estimate": 1250,
                        "estimated_cost_usd": 0.0,
                        "cost_tracking_mode": "rate_card",
                    },
                    "attempt_summary": {
                        "attempt_count": 2,
                        "models_tried": ["gemini-3.5-flash", "gemini-2.5-flash"],
                        "retryable_failure_count": 1,
                        "fallback_path_used": True,
                        "primary_failure_category": "quota_exhausted",
                    },
                    "attempts": [{"model": "gemini-3.5-flash"}, {"model": "gemini-2.5-flash"}],
                }
            },
        )
        session.commit()

        payload = LLMUsageRepository.to_dict(record)
        assert payload["report_id"] == 12
        assert payload["run_id"] == 34
        assert payload["model"] == "gemini-3.5-flash"
        assert payload["total_token_estimate"] == 1250
        assert payload["fallback_path_used"] is True
        assert payload["models_tried"] == ["gemini-3.5-flash", "gemini-2.5-flash"]
        assert payload["observability"]["latency_ms"] == 123.4
    finally:
        session.close()


def test_analysis_run_repository_marks_run_cancelled() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = AnalysisRunRepository(session)
        run = repository.start("celery", {"topic": "AI"})
        cancelled = repository.mark_cancelled(run.id, "user cancelled")
        session.commit()

        assert cancelled.status == "cancelled"
        assert cancelled.error == "user cancelled"
        assert cancelled.finished_at is not None
        payload = json.loads(cancelled.payload_json)
        assert payload["task_failure_diagnostic"]["error_category"] == "cancelled"
        assert payload["task_failure_diagnostic"]["error_severity"] == "info"
    finally:
        session.close()
