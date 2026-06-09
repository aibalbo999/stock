from __future__ import annotations

from collections.abc import Callable
from typing import Any


def run_maintenance_cleanup_payload(
    payload: dict[str, Any] | None,
    *,
    task_id: str | None,
    session_scope_factory: Callable[[], Any],
    analysis_run_repository_cls: Callable[[Any], Any],
    api_services_factory: Callable[[], Any],
    stale_running_before_func: Callable[[dict], Any],
    payload_datetime_func: Callable[[dict, str], Any],
) -> dict[str, Any]:
    cleanup_payload = payload or {}
    with session_scope_factory() as session:
        run = analysis_run_repository_cls(session).start(
            "celery_maintenance_cleanup",
            {
                "task": "maintenance_cleanup",
                "payload": cleanup_payload,
                "celery_task_id": task_id,
            },
        )
        run_id = run.id
    try:
        result = (
            api_services_factory()
            .data_operations_api()
            .maintenance_cleanup(
                failed_runs=bool(cleanup_payload.get("failed_runs", False)),
                orphan_report_refs=bool(cleanup_payload.get("orphan_report_refs", True)),
                latest_reports_only=bool(cleanup_payload.get("latest_reports_only", True)),
                stale_running_before=stale_running_before_func(cleanup_payload),
                runs_before=payload_datetime_func(cleanup_payload, "runs_before"),
                reports_before=payload_datetime_func(cleanup_payload, "reports_before"),
            )
        )
        with session_scope_factory() as session:
            repository = analysis_run_repository_cls(session)
            repository.update_payload(
                run_id,
                {
                    "task": "maintenance_cleanup",
                    "payload": cleanup_payload,
                    "celery_task_id": task_id,
                    "result": result,
                },
            )
            repository.mark_success(run_id, report_id=None)
        return {
            "task_id": task_id,
            "run_id": run_id,
            "result": result,
        }
    except Exception as exc:
        with session_scope_factory() as session:
            analysis_run_repository_cls(session).mark_failed(run_id, str(exc))
        raise
