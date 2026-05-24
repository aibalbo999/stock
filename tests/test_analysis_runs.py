from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.services.persistence import AnalysisRunRepository


def test_analysis_run_lifecycle() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = AnalysisRunRepository(session)
        run = repository.start("api_sync", {"topic": "AI 產業鏈"})
        session.commit()

        repository.mark_success(run.id, report_id=123, output_path="reports/demo.md")
        session.commit()
        latest = repository.latest(1)[0]

        assert latest.status == "success"
        assert latest.report_id == 123
        assert latest.output_path == "reports/demo.md"
        assert latest.finished_at is not None
    finally:
        session.close()


def test_analysis_run_failed_state() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = AnalysisRunRepository(session)
        run = repository.start("celery", {"topic": "AI 產業鏈"})
        session.commit()

        repository.mark_failed(run.id, "boom")
        session.commit()

        assert repository.latest(1)[0].status == "failed"
        assert repository.latest(1)[0].error == "boom"
    finally:
        session.close()


def test_analysis_run_get_and_delete() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = AnalysisRunRepository(session)
        run = repository.start("test", {"topic": "AI 產業鏈"})
        session.commit()

        assert repository.get(run.id).source == "test"
        assert repository.delete(run.id) is True
        session.commit()
        assert repository.get(run.id) is None
        assert repository.delete(run.id) is False
    finally:
        session.close()


def test_get_by_celery_task_id() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = AnalysisRunRepository(session)
        run = repository.start(
            "celery",
            {"request": {"topic": "AI 產業鏈"}, "celery_task_id": "task-abc"},
        )
        repository.start("celery", {"request": {"topic": "other"}})
        session.commit()

        assert repository.get_by_celery_task_id("task-abc").id == run.id
        assert repository.get_by_celery_task_id("missing") is None
    finally:
        session.close()


def test_mark_stale_running_failed_only_updates_old_running_runs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = AnalysisRunRepository(session)
        stale = repository.start("celery", {"topic": "old"})
        stale.started_at = datetime.utcnow() - timedelta(hours=2)
        fresh = repository.start("celery", {"topic": "fresh"})
        successful = repository.start("celery", {"topic": "success"})
        successful.started_at = datetime.utcnow() - timedelta(hours=2)
        repository.mark_success(successful.id, report_id=123)
        session.commit()

        marked = repository.mark_stale_running_failed(datetime.utcnow() - timedelta(hours=1), "timeout")
        session.commit()

        assert marked == 1
        assert repository.get(stale.id).status == "failed"
        assert repository.get(stale.id).error == "timeout"
        assert repository.get(stale.id).finished_at is not None
        assert repository.get(fresh.id).status == "running"
        assert repository.get(successful.id).status == "success"
    finally:
        session.close()
