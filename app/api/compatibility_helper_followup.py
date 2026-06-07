from __future__ import annotations

from collections.abc import Callable
from typing import Any


FOLLOW_UP_COMPATIBILITY_HELPER_NAMES = (
    "load_report_follow_up_context",
    "prepare_follow_up_report_context",
    "refresh_market_data_for_report",
    "get_report_follow_up_plan",
    "maybe_auto_start_required_follow_up",
    "run_required_follow_up_background",
    "run_report_follow_up",
)


def follow_up_compatibility_helper_namespace(
    api_compatibility_provider: Callable[[], Any],
) -> dict[str, object]:
    def api_compatibility() -> Any:
        return api_compatibility_provider()

    def load_report_follow_up_context(report_id):
        return api_compatibility().load_report_follow_up_context(report_id)

    async def prepare_follow_up_report_context(context, request, actions):
        return await api_compatibility().prepare_follow_up_report_context(context, request, actions)

    async def refresh_market_data_for_report(request):
        return await api_compatibility().refresh_market_data_for_report(request)

    def get_report_follow_up_plan(report_id):
        return api_compatibility().get_report_follow_up_plan(report_id)

    async def maybe_auto_start_required_follow_up(report_id, run_in_background=True):
        return await api_compatibility().maybe_auto_start_required_follow_up(
            report_id,
            run_in_background,
        )

    async def run_required_follow_up_background(report_id, payload):
        await api_compatibility().run_required_follow_up_background(report_id, payload)

    async def run_report_follow_up(report_id, payload=None):
        return await api_compatibility().run_report_follow_up(report_id, payload)

    helpers = locals()
    return {name: helpers[name] for name in FOLLOW_UP_COMPATIBILITY_HELPER_NAMES}
