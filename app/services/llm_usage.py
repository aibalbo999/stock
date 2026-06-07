from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from app.db.session import session_scope
from app.services.persistence import LLMUsageRepository


LOGGER = logging.getLogger(__name__)


def record_llm_usage_from_report_execution(
    report_execution: dict | None,
    *,
    operation: str = "report_generation",
    report_id: int | None = None,
    run_id: int | None = None,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
    logger: logging.Logger | None = None,
) -> dict | None:
    """Persist local LLM usage telemetry without making report generation fragile."""
    try:
        with session_scope_factory() as session:
            record = llm_usage_repository_cls(session).create_from_report_execution(
                operation=operation,
                report_execution=report_execution,
                report_id=report_id,
                run_id=run_id,
            )
        return llm_usage_repository_cls.to_dict(record) if record is not None else None
    except Exception as exc:
        (logger or LOGGER).debug("failed to persist LLM usage telemetry: %s", exc, exc_info=True)
        return None


def list_llm_usage_records(
    *,
    limit: int = 50,
    session_scope_factory: Callable[[], AbstractContextManager] = session_scope,
    llm_usage_repository_cls: type[LLMUsageRepository] = LLMUsageRepository,
) -> list[dict[str, Any]]:
    with session_scope_factory() as session:
        records = llm_usage_repository_cls(session).latest(max(1, min(int(limit), 500)))
    return [llm_usage_repository_cls.to_dict(record) for record in records]
