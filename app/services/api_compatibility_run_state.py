from __future__ import annotations

from typing import Any


class RunStateCompatibilityMixin:
    """Legacy analysis run-state delegates for app.api.main imports."""

    api_services: Any

    def safe_mark_run_failed(self, run_id: int, error: str) -> None:
        return self.api_services.run_state().safe_mark_failed(run_id, error)

    def safe_update_run_success(self, run_id: int, payload: dict, report_id: int) -> bool:
        return self.api_services.run_state().safe_update_success(run_id, payload, report_id)
