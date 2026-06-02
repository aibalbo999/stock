import json
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.services.persistence import AnalysisRunRepository
from app.services.workflow_checkpoint import (
    DISCOVERED_PIPELINE_STEPS,
    WorkflowCheckpointRecorder,
    workflow_run_summary,
)


def test_workflow_checkpoint_records_step_lifecycle_and_summary() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    ticks = iter(
        [
            datetime(2026, 5, 31, 9, 0, 0),
            datetime(2026, 5, 31, 9, 0, 1),
            datetime(2026, 5, 31, 9, 0, 3),
        ]
    )

    @contextmanager
    def session_scope():
        session = session_factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    with session_scope() as session:
        run = AnalysisRunRepository(session).start("pipeline_ai_discovery", {"request": {"topic": "AI"}})
        run_id = run.id

    recorder = WorkflowCheckpointRecorder(session_scope_factory=session_scope, clock=lambda: next(ticks))

    assert recorder.initialize(run_id, "ai_discovered_topic_pipeline", DISCOVERED_PIPELINE_STEPS) is True
    assert recorder.start_step(run_id, "topic_discovery", {"topic": "AI"}) is True
    assert recorder.complete_step(run_id, "topic_discovery", {"candidate_count": 3}) is True

    with session_scope() as session:
        payload = json.loads(AnalysisRunRepository(session).get(run_id).payload_json)

    workflow = payload["workflow"]
    first_step = workflow["steps"][0]
    assert workflow["name"] == "ai_discovered_topic_pipeline"
    assert workflow["status"] == "running"
    assert workflow["resume"]["resume_from_step"] == "source_ingestion"
    assert workflow["resume"]["completed_steps"] == ["topic_discovery"]
    assert workflow["resume"]["pending_steps"][0] == "source_ingestion"
    assert first_step["name"] == "topic_discovery"
    assert first_step["status"] == "success"
    assert first_step["summary"] == {"topic": "AI", "candidate_count": 3}
    assert first_step["duration_ms"] == 2000


def test_workflow_checkpoint_can_merge_completed_workflow_into_final_payload() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 5, 31, 10, 0, 0)

    @contextmanager
    def session_scope():
        session = session_factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    with session_scope() as session:
        run = AnalysisRunRepository(session).start("pipeline_api", {"request": {"topic": "機器人"}})
        run_id = run.id

    recorder = WorkflowCheckpointRecorder(session_scope_factory=session_scope, clock=lambda: now)
    recorder.initialize(run_id, "standard_report_pipeline", ["pre_report_refresh", "report_build"])
    recorder.start_step(run_id, "report_build")
    recorder.complete_step(run_id, "report_build", {"report_id": 7})

    final_payload = recorder.complete_workflow_payload(run_id, {"request": {"topic": "機器人"}, "report_id": 7})

    assert final_payload["workflow"]["status"] == "success"
    assert final_payload["workflow"]["finished_at"] == now.isoformat()
    assert final_payload["workflow"]["current_step"] is None
    assert final_payload["workflow"]["resume"]["resumable"] is False
    assert final_payload["workflow"]["resume"]["resume_from_step"] is None
    assert final_payload["workflow"]["steps"][1]["summary"]["report_id"] == 7


def test_workflow_checkpoint_can_merge_running_workflow_into_intermediate_payload() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 5, 31, 10, 30, 0)

    @contextmanager
    def session_scope():
        session = session_factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    with session_scope() as session:
        run = AnalysisRunRepository(session).start("celery", {"request": {"topic": "AI"}})
        run_id = run.id

    recorder = WorkflowCheckpointRecorder(session_scope_factory=session_scope, clock=lambda: now)
    recorder.initialize(run_id, "celery_report_task", ["pre_report_refresh"])
    recorder.start_step(run_id, "pre_report_refresh", {"topic": "AI"})

    payload = recorder.payload_with_current_workflow(run_id, {"request": {"topic": "AI"}, "ingestion": {}})

    assert payload["workflow"]["status"] == "running"
    assert payload["workflow"]["current_step"] == "pre_report_refresh"
    assert payload["workflow"]["resume"]["resumable"] is True
    assert payload["workflow"]["resume"]["resume_from_step"] == "pre_report_refresh"
    assert payload["ingestion"] == {}


def test_workflow_checkpoint_failure_is_non_blocking_for_missing_run() -> None:
    recorder = WorkflowCheckpointRecorder(session_scope_factory=lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert recorder.initialize(999, "workflow", ["step"]) is False
    assert recorder.start_step(999, "step") is False
    assert recorder.complete_step(999, "step") is False
    assert recorder.fail_step(999, "step", "failed") is False
    assert recorder.complete_workflow_payload(999, {"ok": True}) == {"ok": True}


def test_workflow_checkpoint_marks_failed_step_and_duration() -> None:
    start = datetime(2026, 5, 31, 11, 0, 0)
    fail = start + timedelta(seconds=5)
    payload = WorkflowCheckpointRecorder.initialize_payload(
        {"request": {"topic": "AI"}},
        "workflow",
        ["source_ingestion"],
        start.isoformat(),
    )
    payload = WorkflowCheckpointRecorder.start_step_payload(
        payload,
        "source_ingestion",
        start.isoformat(),
        {"query_count": 12},
    )
    payload = WorkflowCheckpointRecorder.fail_step_payload(
        payload,
        "source_ingestion",
        "timeout",
        fail.isoformat(),
    )

    workflow = payload["workflow"]
    step = workflow["steps"][0]
    assert workflow["status"] == "failed"
    assert workflow["current_step"] == "source_ingestion"
    assert workflow["resume"]["blocked_by_failure"] is True
    assert workflow["resume"]["resume_from_step"] == "source_ingestion"
    assert workflow["resume"]["failed_steps"] == ["source_ingestion"]
    assert step["status"] == "failed"
    assert step["duration_ms"] == 5000
    assert step["error"] == "timeout"


def test_workflow_checkpoint_resume_state_tracks_next_step_after_initialization() -> None:
    payload = WorkflowCheckpointRecorder.initialize_payload(
        {"request": {"topic": "AI"}},
        "workflow",
        ["topic_discovery", "source_ingestion"],
        datetime(2026, 5, 31, 12, 0, 0).isoformat(),
    )

    assert payload["workflow"]["resume"] == {
        "resumable": True,
        "resume_from_step": "topic_discovery",
        "next_incomplete_step": "topic_discovery",
        "current_step": None,
        "completed_steps": [],
        "failed_steps": [],
        "running_steps": [],
        "pending_steps": ["topic_discovery", "source_ingestion"],
        "blocked_by_failure": False,
    }


def test_workflow_run_summary_exposes_progress_and_resume_hint() -> None:
    payload = WorkflowCheckpointRecorder.initialize_payload(
        {},
        "ai_discovered_topic_pipeline",
        ["topic_discovery", "source_ingestion", "report_build"],
        "2026-05-31T09:00:00",
    )
    payload = WorkflowCheckpointRecorder.complete_step_payload(
        payload,
        "topic_discovery",
        "2026-05-31T09:01:00",
    )
    payload = WorkflowCheckpointRecorder.fail_step_payload(
        payload,
        "source_ingestion",
        "timeout",
        "2026-05-31T09:02:00",
    )

    summary = workflow_run_summary(payload["workflow"])

    assert summary == {
        "name": "ai_discovered_topic_pipeline",
        "status": "failed",
        "total_steps": 3,
        "completed_steps_count": 1,
        "failed_steps_count": 1,
        "running_steps_count": 0,
        "pending_steps_count": 1,
        "progress_pct": 1 / 3,
        "current_step": "source_ingestion",
        "next_incomplete_step": "source_ingestion",
        "resume_from_step": "source_ingestion",
        "resumable": True,
        "blocked_by_failure": True,
        "resume_hint": "可從 source_ingestion 重新啟動或人工接續。",
    }
