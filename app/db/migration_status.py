from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from app.core.config import get_settings


DEFAULT_ALEMBIC_CONFIG = Path("alembic.ini")


def alembic_config(
    database_url: str | None = None,
    config_path: str | Path = DEFAULT_ALEMBIC_CONFIG,
) -> Any:
    from alembic.config import Config

    settings = get_settings()
    config = Config(str(config_path))
    url = database_url or settings.database_url
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def run_alembic_upgrade(
    database_url: str | None = None,
    revision: str = "head",
    config_path: str | Path = DEFAULT_ALEMBIC_CONFIG,
) -> None:
    from alembic import command

    command.upgrade(
        alembic_config(database_url=database_url, config_path=config_path),
        revision,
    )


def db_migration_status(
    bind: Engine | Connection | None = None,
    database_url: str | None = None,
    config_path: str | Path = DEFAULT_ALEMBIC_CONFIG,
) -> dict[str, Any]:
    try:
        from alembic.script import ScriptDirectory

        config = alembic_config(database_url=database_url, config_path=config_path)
        script = ScriptDirectory.from_config(config)
        head_revisions = sorted(script.get_heads())
        current_revisions = sorted(_current_revisions(bind=bind, database_url=database_url))
        return {
            "ok": True,
            "config_path": str(config_path),
            "current_revision": current_revisions[0] if len(current_revisions) == 1 else None,
            "current_revisions": current_revisions,
            "head_revision": head_revisions[0] if len(head_revisions) == 1 else None,
            "head_revisions": head_revisions,
            "version_table_present": bool(current_revisions),
            "up_to_date": bool(head_revisions) and set(current_revisions) == set(head_revisions),
        }
    except Exception as exc:
        return _unavailable_migration_status(config_path=config_path, error=str(exc))


def _unavailable_migration_status(
    config_path: str | Path,
    error: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "config_path": str(config_path),
        "current_revision": None,
        "current_revisions": [],
        "head_revision": None,
        "head_revisions": [],
        "version_table_present": False,
        "up_to_date": False,
        "error": error,
    }


def _current_revisions(
    bind: Engine | Connection | None = None,
    database_url: str | None = None,
) -> tuple[str, ...]:
    if isinstance(bind, Connection):
        from alembic.runtime.migration import MigrationContext

        context = MigrationContext.configure(bind)
        return tuple(context.get_current_heads())
    if isinstance(bind, Engine):
        from alembic.runtime.migration import MigrationContext

        with bind.connect() as connection:
            context = MigrationContext.configure(connection)
            return tuple(context.get_current_heads())

    url = database_url or get_settings().database_url
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )
    try:
        from alembic.runtime.migration import MigrationContext

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return tuple(context.get_current_heads())
    finally:
        engine.dispose()
