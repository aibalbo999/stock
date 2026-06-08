from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.api.data_operation_error_context import data_operation_error_context
from app.api.task_submission_errors import (
    raise_task_queue_unavailable,
    raise_task_submission_failed,
)


def submit_generate_report_task(
    services: Any,
    request: Any,
    *,
    async_report_validation_error_cls: type[Exception],
    task_queue_unavailable_error_cls: type[Exception],
) -> dict:
    try:
        return services.run_task_api().generate_report_async(request)
    except async_report_validation_error_cls as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except task_queue_unavailable_error_cls as exc:
        raise_task_queue_unavailable(exc, operation="generate_report")
    except Exception as exc:
        raise_task_submission_failed(exc, operation="generate_report")


def submit_discovered_report_task(
    services: Any,
    payload: Any,
    *,
    async_report_validation_error_cls: type[Exception],
    task_queue_unavailable_error_cls: type[Exception],
) -> dict:
    try:
        return services.run_task_api().generate_discovered_report_async(payload)
    except async_report_validation_error_cls as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except task_queue_unavailable_error_cls as exc:
        raise_task_queue_unavailable(exc, operation="run_discovered")
    except Exception as exc:
        raise_task_submission_failed(exc, operation="run_discovered")


def submit_data_operation_task(
    services: Any,
    operation: str,
    payload: dict,
    *,
    async_report_validation_error_cls: type[Exception],
    task_queue_unavailable_error_cls: type[Exception],
) -> dict:
    error_context = data_operation_error_context(operation, payload)
    try:
        return services.run_task_api().queue_data_operation(operation, payload)
    except async_report_validation_error_cls as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except task_queue_unavailable_error_cls as exc:
        raise_task_queue_unavailable(
            exc,
            operation=operation,
            context=error_context,
        )
    except Exception as exc:
        raise_task_submission_failed(
            exc,
            operation=operation,
            context=error_context,
        )
