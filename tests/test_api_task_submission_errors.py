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
    assert raised.value.detail["error_summary"] == "背景任務佇列或背景執行器異常"
    assert raised.value.detail["next_steps"] == [
        "到系統設定 > 維護 > 背景任務觀測確認提交、佇列與背景執行器狀態。",
        "執行「背景執行器連線檢查」診斷；必要時重新啟動背景任務服務。",
    ]
    assert "Redis/Celery" not in str(raised.value.detail)
    assert "worker" not in str(raised.value.detail)
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
