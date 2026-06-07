from __future__ import annotations

from collections.abc import Callable
from typing import Any


RUN_STATE_COMPATIBILITY_HELPER_NAMES = (
    "safe_mark_run_failed",
    "safe_update_run_success",
)


def run_state_compatibility_helper_namespace(
    api_compatibility_provider: Callable[[], Any],
) -> dict[str, object]:
    def api_compatibility() -> Any:
        return api_compatibility_provider()

    def safe_mark_run_failed(run_id, error):
        return api_compatibility().safe_mark_run_failed(run_id, error)

    def safe_update_run_success(run_id, payload, report_id):
        return api_compatibility().safe_update_run_success(run_id, payload, report_id)

    helpers = locals()
    return {name: helpers[name] for name in RUN_STATE_COMPATIBILITY_HELPER_NAMES}
