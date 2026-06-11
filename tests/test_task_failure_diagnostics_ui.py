from __future__ import annotations

from pathlib import Path

from app.ui.task_failure_diagnostics import TASK_FAILURE_ACTION_ROUTE_DETAILS


def test_task_failure_catalog_lives_outside_diagnostics_row_builders() -> None:
    diagnostics_source = Path("app/ui/task_failure_diagnostics.py").read_text()
    catalog_path = Path("app/ui/task_failure_catalog.py")

    assert catalog_path.exists()
    catalog_source = catalog_path.read_text()
    assert "from app.ui.task_failure_catalog import (" in diagnostics_source
    assert "TASK_FAILURE_ACTION_ROUTE_DETAILS" in catalog_source
    assert "def task_failure_action_route(" in catalog_source
    assert "def task_failure_operation_label(" in catalog_source
    assert "CATEGORY_LABELS = {" not in diagnostics_source
    assert "def _is_external_config_failure(" not in diagnostics_source


def test_task_failure_action_route_details_use_operator_language_for_fallbacks() -> None:
    retry_detail = TASK_FAILURE_ACTION_ROUTE_DETAILS["一鍵重試"]

    assert "切換後援模型或資料源" in retry_detail
    assert "fallback" not in retry_detail
