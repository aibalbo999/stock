from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from app.db.session import session_scope
from app.services.persistence import AnalysisRunRepository


class TaskCancelledError(RuntimeError):
    def __init__(self, run_id: int) -> None:
        super().__init__("task cancellation requested")
        self.run_id = run_id


def task_cancellation_requested(
    run_id: int,
    *,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
) -> bool:
    try:
        with session_scope_factory() as session:
            run = analysis_run_repository_cls(session).get(run_id)
    except Exception:
        return False
    payload = _parse_payload(getattr(run, "payload_json", None)) if run is not None else {}
    return bool(payload.get("cancel_requested"))


def raise_if_task_cancelled(
    run_id: int,
    *,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
) -> None:
    if task_cancellation_requested(
        run_id,
        session_scope_factory=session_scope_factory,
        analysis_run_repository_cls=analysis_run_repository_cls,
    ):
        raise TaskCancelledError(run_id)


def mark_run_cancelled(
    run_id: int,
    *,
    reason: str = "task cancellation requested",
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    analysis_run_repository_cls: type[AnalysisRunRepository] = AnalysisRunRepository,
) -> None:
    with session_scope_factory() as session:
        repository = analysis_run_repository_cls(session)
        mark_cancelled = getattr(repository, "mark_cancelled", None)
        if callable(mark_cancelled):
            mark_cancelled(run_id, reason)
        else:
            repository.mark_failed(run_id, reason)


def _parse_payload(payload_json: str | None) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
