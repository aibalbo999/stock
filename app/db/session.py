from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    settings = get_settings()
    mode = str(getattr(settings, "database_init_mode", "create_all") or "create_all")
    normalized_mode = mode.strip().lower().replace("-", "_")
    if normalized_mode in {"alembic", "migration", "migrations"}:
        from app.db.migration_status import run_alembic_upgrade

        run_alembic_upgrade()
        return
    if normalized_mode in {"none", "off", "disabled"}:
        return
    if normalized_mode not in {"create_all", "createall", "metadata"}:
        raise ValueError(
            "Unsupported DATABASE_INIT_MODE. Use create_all, alembic, or none."
        )
    _guard_create_all_for_database_url(settings)
    from app.db.models import Base

    Base.metadata.create_all(bind=engine)


def _guard_create_all_for_database_url(settings) -> None:
    database_url = str(getattr(settings, "database_url", "") or "")
    if not database_url or database_url.startswith("sqlite"):
        return
    if bool(getattr(settings, "database_allow_create_all_non_sqlite", False)):
        return
    raise ValueError(
        "DATABASE_INIT_MODE=create_all is only allowed for local SQLite. "
        "Use DATABASE_INIT_MODE=alembic for PostgreSQL/MySQL deployments, "
        "or set DATABASE_ALLOW_CREATE_ALL_NON_SQLITE=true only for a controlled one-off bootstrap."
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
