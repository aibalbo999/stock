from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.task_submission_errors import (
    raise_task_queue_unavailable,
    raise_task_submission_failed,
)


def test_raise_task_queue_unavailable_preserves_structured_detail() -> None:
    with pytest.raises(HTTPException) as raised:
        raise_task_queue_unavailable(
            RuntimeError("task queue unavailable"),
            operation="market_refresh",
            context={"task": "data_operation"},
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "task_queue_unavailable"
    assert raised.value.detail["operation"] == "market_refresh"
    assert raised.value.detail["retryable"] is True
    assert raised.value.detail["error_type"] == "RuntimeError"
    assert raised.value.detail["error_category"] == "task_queue"
    assert raised.value.detail["error_summary"] == "Redis/Celery queue 或 worker 異常"
    assert raised.value.detail["context"] == {"task": "data_operation"}


def test_raise_task_submission_failed_preserves_structured_detail() -> None:
    with pytest.raises(HTTPException) as raised:
        raise_task_submission_failed(
            RuntimeError("service wiring missing data task"),
            operation="market_refresh",
            context={"task": "data_operation"},
        )

    assert raised.value.status_code == 500
    assert raised.value.detail["code"] == "background_task_submission_failed"
    assert raised.value.detail["operation"] == "market_refresh"
    assert raised.value.detail["retryable"] is False
    assert raised.value.detail["error_type"] == "RuntimeError"
    assert raised.value.detail["error_category"] == "unknown"
    assert raised.value.detail["error_summary"] == "未分類任務失敗"
    assert raised.value.detail["context"] == {"task": "data_operation"}


def test_raise_task_submission_failed_remaps_raw_queue_errors_to_503() -> None:
    with pytest.raises(HTTPException) as raised:
        raise_task_submission_failed(
            ConnectionError("redis connection refused"),
            operation="market_refresh",
            context={"task": "data_operation", "failure_stage": "task_submission"},
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "task_queue_unavailable"
    assert raised.value.detail["operation"] == "market_refresh"
    assert raised.value.detail["retryable"] is True
    assert raised.value.detail["error_type"] == "ConnectionError"
    assert raised.value.detail["error_category"] == "task_queue"
    assert raised.value.detail["context"] == {
        "task": "data_operation",
        "failure_stage": "task_submission",
    }
