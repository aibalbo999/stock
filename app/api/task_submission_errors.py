from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException

from app.api.error_details import task_queue_unavailable_detail, task_submission_failed_detail

TASK_QUEUE_ERROR_CATEGORIES = {"task_queue"}


def raise_task_queue_unavailable(
    exc: Exception,
    *,
    operation: str | None = None,
    context: dict | None = None,
) -> NoReturn:
    raise HTTPException(
        status_code=503,
        detail=task_queue_unavailable_detail(exc, operation=operation, context=context),
    ) from exc


def raise_task_submission_failed(
    exc: Exception,
    *,
    operation: str | None = None,
    context: dict | None = None,
) -> NoReturn:
    detail = task_submission_failed_detail(exc, operation=operation, context=context)
    if detail.get("error_category") in TASK_QUEUE_ERROR_CATEGORIES:
        raise HTTPException(
            status_code=503,
            detail=task_queue_unavailable_detail(exc, operation=operation, context=context),
        ) from exc
    raise HTTPException(
        status_code=500,
        detail=detail,
    ) from exc
