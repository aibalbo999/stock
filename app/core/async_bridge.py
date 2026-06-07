from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run_async_from_sync(coro: Coroutine[Any, Any, T], *, operation: str) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise RuntimeError(
        f"{operation} cannot run inside an active event loop; call the async service "
        "directly or enqueue the background task endpoint instead."
    )
