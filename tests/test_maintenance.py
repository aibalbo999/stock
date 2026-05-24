from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, GeneratedReport
from app.models.schemas import ReportRequest, ReportResponse
from app.services.persistence import AnalysisRunRepository, ReportRepository


def test_cleanup_failed_runs_and_old_reports() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        runs = AnalysisRunRepository(session)
        reports = ReportRepository(session)
        failed = runs.start("test", {})
        runs.mark_failed(failed.id, "boom")
        successful = runs.start("test", {})
        runs.mark_success(successful.id, report_id=1)
        report = reports.create(
            ReportRequest(topic="AI 產業鏈"),
            ReportResponse(title="old", markdown="# old"),
        )
        report.generated_at = datetime.utcnow() - timedelta(days=10)
        session.commit()

        assert runs.delete_failed() == 1
        assert reports.delete_before(datetime.utcnow() - timedelta(days=1)) == 1
        assert session.get(GeneratedReport, report.id) is None
        assert runs.latest(10)[0].status == "success"
    finally:
        session.close()


def test_clear_orphan_report_refs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        runs = AnalysisRunRepository(session)
        run = runs.start("test", {})
        runs.mark_success(run.id, report_id=999)
        session.commit()

        assert runs.orphan_report_ids() == [run.id]
        assert runs.clear_orphan_report_refs() == 1
        session.commit()
        assert runs.get(run.id).report_id is None
    finally:
        session.close()
