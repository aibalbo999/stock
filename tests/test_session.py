from types import SimpleNamespace

import pytest

from app.db import session as db_session
from app.db.session import session_scope
from app.services.persistence import AnalysisRunRepository


def test_session_scope_keeps_committed_attributes_readable() -> None:
    with session_scope() as session:
        run = AnalysisRunRepository(session).start("test", {"topic": "AI 產業鏈"})

    assert run.id is not None
    assert run.source == "test"
    assert run.status == "running"


def test_init_db_uses_create_all_by_default(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: SimpleNamespace(database_init_mode="create_all"),
    )
    monkeypatch.setattr(db_session, "engine", object())

    def fake_create_all(bind):
        captured["bind"] = bind

    from app.db.models import Base

    monkeypatch.setattr(Base.metadata, "create_all", fake_create_all)

    db_session.init_db()

    assert captured["bind"] is db_session.engine


def test_init_db_can_run_alembic_migrations(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: SimpleNamespace(database_init_mode="alembic"),
    )

    from app.db import migration_status
    from app.db.models import Base

    monkeypatch.setattr(migration_status, "run_alembic_upgrade", lambda: captured.setdefault("migrated", True))
    monkeypatch.setattr(
        Base.metadata,
        "create_all",
        lambda bind: pytest.fail("create_all should not run in alembic init mode"),
    )

    db_session.init_db()

    assert captured == {"migrated": True}


def test_init_db_blocks_create_all_for_non_sqlite_without_explicit_override(monkeypatch) -> None:
    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: SimpleNamespace(
            database_init_mode="create_all",
            database_url="postgresql://user:password@example.test/db",
            database_allow_create_all_non_sqlite=False,
        ),
    )
    from app.db.models import Base

    monkeypatch.setattr(
        Base.metadata,
        "create_all",
        lambda bind: pytest.fail("create_all should be blocked for non-SQLite deployment DBs"),
    )

    with pytest.raises(ValueError, match="DATABASE_INIT_MODE=create_all is only allowed for local SQLite"):
        db_session.init_db()


def test_init_db_allows_non_sqlite_create_all_only_with_explicit_override(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: SimpleNamespace(
            database_init_mode="create_all",
            database_url="postgresql://user:password@example.test/db",
            database_allow_create_all_non_sqlite=True,
        ),
    )
    monkeypatch.setattr(db_session, "engine", object())

    def fake_create_all(bind):
        captured["bind"] = bind

    from app.db.models import Base

    monkeypatch.setattr(Base.metadata, "create_all", fake_create_all)

    db_session.init_db()

    assert captured["bind"] is db_session.engine


def test_init_db_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: SimpleNamespace(database_init_mode="none"),
    )
    from app.db.models import Base

    monkeypatch.setattr(
        Base.metadata,
        "create_all",
        lambda bind: pytest.fail("create_all should not run when init is disabled"),
    )

    db_session.init_db()
