import asyncio

import pytest

from app.core.async_bridge import run_async_from_sync


async def _async_value() -> str:
    return "ready"


def test_run_async_from_sync_runs_without_active_event_loop() -> None:
    assert run_async_from_sync(_async_value(), operation="test.operation") == "ready"


def test_run_async_from_sync_rejects_active_event_loop() -> None:
    async def run_inside_loop() -> None:
        with pytest.raises(RuntimeError, match="test.operation cannot run inside an active event loop"):
            run_async_from_sync(_async_value(), operation="test.operation")

    asyncio.run(run_inside_loop())
