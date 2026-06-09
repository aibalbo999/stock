from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.services.task_cancellation import TaskCancelledError


def run_generate_report_payload(
    payload: dict[str, Any],
    *,
    task_id: str | None,
    session_scope_factory: Callable[[], Any],
    analysis_run_repository_cls: Callable[[Any], Any],
    report_request_cls: Any,
    build_run_payload_func: Callable[[dict, str | None, dict | None], dict],
    workflow_factory: Callable[[], Any],
    workflow_steps: Sequence[str],
    raise_if_cancelled_func: Callable[[int], None],
    mark_cancelled_func: Callable[[int], None],
    pipeline_factory: Callable[[int | None], Any],
    run_async_func: Callable[..., Any],
    pre_report_refresh_operation: str,
    report_build_service_factory: Callable[[], Any],
    follow_up_action_planner_factory: Callable[[], Any],
    execute_follow_up_actions_func: Callable[[list, Any], dict],
    create_report_with_retention_func: Callable[[Any, Any], tuple[int, dict]],
    record_llm_usage_func: Callable[..., Any],
    write_report_file_with_retention_func: Callable[[Any, Any], dict],
    combined_report_retention_func: Callable[[dict | None, dict | None], dict],
) -> dict[str, Any]:
    with session_scope_factory() as session:
        run = analysis_run_repository_cls(session).start(
            "celery", build_run_payload_func(payload, task_id, None)
        )
        run_id = run.id
    request = report_request_cls.model_validate(payload)
    workflow = workflow_factory()
    workflow.initialize(run_id, "celery_report_task", list(workflow_steps))
    current_step = "pre_report_refresh"
    try:
        raise_if_cancelled_func(run_id)
        workflow.start_step(run_id, current_step)
        ingestion_summary = run_async_func(
            pipeline_factory(run_id).pre_report_refresh(request),
            operation=pre_report_refresh_operation,
        )
        raise_if_cancelled_func(run_id)
        workflow.complete_step(
            run_id,
            current_step,
            {
                "news_count": (ingestion_summary.get("news") or {}).get("count", 0),
                "company_filing_count": (ingestion_summary.get("company_filings") or {}).get(
                    "stored_count", 0
                ),
            },
        )
        with session_scope_factory() as session:
            analysis_run_repository_cls(session).update_payload(
                run_id,
                workflow.payload_with_current_workflow(
                    run_id,
                    build_run_payload_func(payload, task_id, ingestion_summary),
                ),
            )
        current_step = "report_build"
        raise_if_cancelled_func(run_id)
        workflow.start_step(run_id, current_step)
        report_result = report_build_service_factory().build(
            request,
            source_count=(ingestion_summary.get("news") or {}).get("count", 0),
        )
        raise_if_cancelled_func(run_id)
        response = report_result["response"]
        quality_gate = report_result["quality_gate"]
        workflow.complete_step(
            run_id,
            current_step,
            {
                "quality_gate_status": quality_gate.get("status"),
                "evidence_count": report_result["evidence_count"],
            },
        )
        follow_up_summary = None
        if quality_gate.get("status") != "ready":
            current_step = "follow_up_actions"
            raise_if_cancelled_func(run_id)
            workflow.start_step(
                run_id, current_step, {"quality_gate_status": quality_gate.get("status")}
            )
            follow_up_actions = follow_up_action_planner_factory().plan(
                request, quality_gate=quality_gate
            )
            if follow_up_actions:
                follow_up_summary = execute_follow_up_actions_func(follow_up_actions, request)
                raise_if_cancelled_func(run_id)
                ingestion_summary = {
                    **ingestion_summary,
                    "follow_up": follow_up_summary,
                }
                report_result = report_build_service_factory().build(
                    request,
                    source_count=(ingestion_summary.get("news") or {}).get("count", 0),
                )
                response = report_result["response"]
                quality_gate = report_result["quality_gate"]
                raise_if_cancelled_func(run_id)
            workflow.complete_step(
                run_id,
                current_step,
                {
                    "action_count": len(follow_up_actions),
                    "stored_count": (follow_up_summary or {})
                    .get("execution_summary", {})
                    .get("stored_count"),
                    "quality_gate_status_after": quality_gate.get("status"),
                },
            )
        current_step = "report_persist"
        raise_if_cancelled_func(run_id)
        workflow.start_step(
            run_id, current_step, {"quality_gate_status": quality_gate.get("status")}
        )
        with session_scope_factory() as session:
            analysis_run_repository_cls(session).update_payload(
                run_id,
                workflow.payload_with_current_workflow(
                    run_id,
                    {
                        **build_run_payload_func(payload, task_id, ingestion_summary),
                        "quality_gate": quality_gate,
                        "follow_up": follow_up_summary,
                        "report_execution": report_result["report_execution"],
                    },
                ),
            )
        raise_if_cancelled_func(run_id)
        report_id, db_retention = create_report_with_retention_func(request, response)
        record_llm_usage_func(
            report_result.get("report_execution"),
            operation="celery_report_generation",
            report_id=report_id,
            run_id=run_id,
        )
        workflow.complete_step(run_id, current_step, {"report_id": report_id})
        file_retention = write_report_file_with_retention_func(request, response)
        path = file_retention["path"]
        retention = combined_report_retention_func(db_retention, file_retention)
        with session_scope_factory() as session:
            repository = analysis_run_repository_cls(session)
            repository.update_payload(
                run_id,
                workflow.complete_workflow_payload(
                    run_id,
                    {
                        **build_run_payload_func(payload, task_id, ingestion_summary),
                        "quality_gate": quality_gate,
                        "follow_up": follow_up_summary,
                        "report_execution": report_result["report_execution"],
                        "retention": retention,
                    },
                ),
            )
            repository.mark_success(run_id, report_id, str(path))
        return {
            "task_id": task_id,
            "run_id": run_id,
            "id": report_id,
            "title": response.title,
            "path": str(path),
            "generated_at": response.generated_at.isoformat(),
            "retention": retention,
        }
    except TaskCancelledError as exc:
        workflow.cancel_step(run_id, current_step, str(exc), {"cancelled": True})
        mark_cancelled_func(run_id)
        return {
            "task_id": task_id,
            "run_id": run_id,
            "cancelled": True,
        }
    except Exception as exc:
        workflow.fail_step(run_id, current_step, str(exc))
        with session_scope_factory() as session:
            analysis_run_repository_cls(session).mark_failed(run_id, str(exc))
        raise
