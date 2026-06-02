from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread
from typing import TypeVar


T = TypeVar("T")


class RagOperationTimeout(TimeoutError):
    pass


def run_with_timeout(
    func: Callable[[], T],
    timeout_seconds: float,
    operation: str,
) -> T:
    if timeout_seconds <= 0:
        return func()

    queue: Queue[tuple[str, T | BaseException]] = Queue(maxsize=1)

    def runner() -> None:
        try:
            queue.put(("ok", func()))
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            queue.put(("error", exc))

    thread = Thread(target=runner, name=f"rag-timeout-{operation}", daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise RagOperationTimeout(f"{operation} timed out after {timeout_seconds:.1f}s")

    try:
        status, value = queue.get_nowait()
    except Empty as exc:  # Defensive guard for unusual thread termination.
        raise RagOperationTimeout(f"{operation} ended without returning a result") from exc
    if status == "error":
        raise value
    return value  # type: ignore[return-value]
