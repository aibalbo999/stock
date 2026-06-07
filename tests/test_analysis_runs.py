import json
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.time import utc_now_naive
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
        run = repository.start(
            "celery",
            {
                "request": {"topic": "AI 產業鏈", "tickers": ["2330"]},
                "celery_task_id": "task-quota",
            },
        )
        session.commit()

        repository.mark_failed(run.id, "RESOURCE_EXHAUSTED quota exceeded")
        session.commit()

        failed = repository.latest(1)[0]
        payload = json.loads(failed.payload_json)

        assert failed.status == "failed"
        assert failed.error == "RESOURCE_EXHAUSTED quota exceeded"
        assert payload["task_failure_diagnostic"]["error_category"] == "quota"
        assert payload["task_failure_diagnostic"]["retryable"] is True
        assert payload["task_failure_diagnostic"]["retry_endpoint"] == "POST /tasks/task-quota/retry"
    finally:
        session.close()


def test_analysis_run_can_be_marked_running_for_resume() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        repository = AnalysisRunRepository(session)
        run = repository.start(
            "pipeline_api",
            {"request": {"topic": "AI 產業鏈"}, "celery_task_id": "task-resume"},
        )
        repository.mark_failed(run.id, "boom")
        session.commit()

        failed_payload = json.loads(repository.get(run.id).payload_json)
        assert failed_payload["task_failure_diagnostic"]["error_category"] == "unknown"

        repository.mark_running(run.id)
        session.commit()

        resumed = repository.get(run.id)
        resumed_payload = json.loads(resumed.payload_json)
        assert resumed.status == "running"
        assert resumed.error is None
        assert resumed.finished_at is None
        assert "task_failure_diagnostic" not in resumed_payload
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
        stale.started_at = utc_now_naive() - timedelta(hours=2)
        fresh = repository.start("celery", {"topic": "fresh"})
        successful = repository.start("celery", {"topic": "success"})
        successful.started_at = utc_now_naive() - timedelta(hours=2)
        repository.mark_success(successful.id, report_id=123)
        session.commit()

        marked = repository.mark_stale_running_failed(utc_now_naive() - timedelta(hours=1), "timeout")
        session.commit()

        assert marked == 1
        assert repository.get(stale.id).status == "failed"
        assert repository.get(stale.id).error == "timeout"
        assert repository.get(stale.id).finished_at is not None
        assert repository.get(fresh.id).status == "running"
        assert repository.get(successful.id).status == "success"
    finally:
        session.close()
