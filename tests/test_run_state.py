from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

from app.services.run_state import RunStateService


@contextmanager
def fake_session_scope():
    yield object()


def test_run_state_updates_existing_run_success() -> None:
    calls = []

    class FakeRepository:
        def __init__(self, session: object) -> None:
            calls.append(("init", session is not None))

        def get(self, run_id: int):
            calls.append(("get", run_id))
            return {"id": run_id}

        def update_payload(self, run_id: int, payload: dict) -> None:
            calls.append(("update_payload", run_id, payload))

        def mark_success(self, run_id: int, report_id: int) -> None:
            calls.append(("mark_success", run_id, report_id))

    service = RunStateService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRepository,
    )

    assert service.safe_update_success(7, {"stage": "done"}, 42) is True
    assert calls == [
        ("init", True),
        ("get", 7),
        ("update_payload", 7, {"stage": "done"}),
        ("mark_success", 7, 42),
    ]


def test_run_state_returns_false_when_run_is_missing() -> None:
    calls = []

    class FakeRepository:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: int):
            calls.append(("get", run_id))
            return None

        def update_payload(self, run_id: int, payload: dict) -> None:
            raise AssertionError("missing run must not be updated")

        def mark_success(self, run_id: int, report_id: int) -> None:
            raise AssertionError("missing run must not be marked successful")

    service = RunStateService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRepository,
    )

    assert service.safe_update_success(404, {}, 1) is False
    assert calls == [("get", 404)]


def test_run_state_merges_payload_updates_without_losing_checkpoint() -> None:
    calls = []
    run = SimpleNamespace(payload_json=json.dumps({"workflow": {"status": "success"}, "report_id": 7}))

    class FakeRepository:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: int):
            calls.append(("get", run_id))
            return run

        def update_payload(self, run_id: int, payload: dict) -> None:
            calls.append(("update_payload", run_id, payload))

    service = RunStateService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRepository,
    )

    assert service.safe_merge_payload(
        7,
        {"workflow_orchestration": {"mode": "prefect_flow", "executed_engine": "prefect"}},
    ) is True
    assert calls == [
        ("get", 7),
        (
            "update_payload",
            7,
            {
                "workflow": {"status": "success"},
                "report_id": 7,
                "workflow_orchestration": {"mode": "prefect_flow", "executed_engine": "prefect"},
            },
        ),
    ]


def test_run_state_merge_payload_returns_false_when_run_is_missing() -> None:
    class FakeRepository:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: int):
            return None

        def update_payload(self, run_id: int, payload: dict) -> None:
            raise AssertionError("missing run must not be updated")

    service = RunStateService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRepository,
    )

    assert service.safe_merge_payload(404, {"workflow_orchestration": {"mode": "local"}}) is False


def test_run_state_safe_mark_failed_swallows_repository_errors() -> None:
    class FailingRepository:
        def __init__(self, session: object) -> None:
            raise RuntimeError("database unavailable")

    service = RunStateService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FailingRepository,
    )

    assert service.safe_mark_failed(7, "boom") is None


def test_run_state_safe_mark_failed_marks_existing_run() -> None:
    calls = []

    class FakeRepository:
        def __init__(self, session: object) -> None:
            pass

        def get(self, run_id: int):
            calls.append(("get", run_id))
            return {"id": run_id}

        def mark_failed(self, run_id: int, error: str) -> None:
            calls.append(("mark_failed", run_id, error))

    service = RunStateService(
        session_scope_factory=fake_session_scope,
        analysis_run_repository_cls=FakeRepository,
    )

    service.safe_mark_failed(7, "boom")

    assert calls == [("get", 7), ("mark_failed", 7, "boom")]
