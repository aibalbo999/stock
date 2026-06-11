from __future__ import annotations

from app.ui.task_failure_diagnostics import TASK_FAILURE_ACTION_ROUTE_DETAILS


def test_task_failure_action_route_details_use_operator_language_for_fallbacks() -> None:
    retry_detail = TASK_FAILURE_ACTION_ROUTE_DETAILS["一鍵重試"]

    assert "切換後援模型或資料源" in retry_detail
    assert "fallback" not in retry_detail
