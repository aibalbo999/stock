from __future__ import annotations

# ruff: noqa: F401

import asyncio
from datetime import date

from app.api.schemas import FollowUpRunRequest
from app.core.config import get_settings
from app.core.time import today_taipei
from app.db.session import init_db, session_scope
from app.services import candidate_revalidation

CORE_EXPORT_NAMES = (
    "asyncio",
    "date",
    "candidate_revalidation",
    "init_db",
    "get_settings",
    "today_taipei",
    "session_scope",
    "FollowUpRunRequest",
)


def compatibility_core_export_namespace() -> dict[str, object]:
    return {name: globals()[name] for name in CORE_EXPORT_NAMES}
