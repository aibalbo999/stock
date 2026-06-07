from pathlib import Path

import pytest

from app.db.models import Base
from app.db.migration_status import alembic_config, db_migration_status, run_alembic_upgrade


def test_alembic_scaffold_exists() -> None:
    assert Path("alembic.ini").exists()
    assert Path("migrations/env.py").exists()
    assert Path("migrations/script.py.mako").exists()
    assert Path("migrations/versions/0001_initial_schema.py").exists()
    assert Path("migrations/versions/0002_add_report_quality_gate_json.py").exists()
    assert Path("migrations/versions/0003_add_llm_usage_records.py").exists()


def test_initial_migration_is_explicit_schema_snapshot() -> None:
    migration = Path("migrations/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert 'revision = "0001_initial_schema"' in migration
    assert "Base.metadata.create_all" not in migration
    assert "Base.metadata.drop_all" not in migration
    assert "op.create_table" in migration
    post_initial_tables = {"llm_usage_records"}
    for table_name in set(Base.metadata.tables) - post_initial_tables:
        assert f'"{table_name}"' in migration


def test_report_quality_gate_migration_adds_structured_payload_column() -> None:
    migration = Path("migrations/versions/0002_add_report_quality_gate_json.py").read_text(encoding="utf-8")

    assert 'revision = "0002_add_report_quality_gate_json"' in migration
    assert 'down_revision = "0001_initial_schema"' in migration
    assert '"quality_gate_json"' in migration
    assert '"generated_reports"' in migration


def test_llm_usage_migration_adds_usage_history_table() -> None:
    migration = Path("migrations/versions/0003_add_llm_usage_records.py").read_text(encoding="utf-8")

    assert 'revision = "0003_add_llm_usage_records"' in migration
    assert 'down_revision = "0002_add_report_quality_gate_json"' in migration
    assert '"llm_usage_records"' in migration
    assert '"total_token_estimate"' in migration


def test_initial_migration_upgrades_to_current_metadata_schema(tmp_path: Path) -> None:
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"

    command.upgrade(alembic_config(database_url=database_url), "head")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert set(Base.metadata.tables).issubset(set(inspector.get_table_names()))
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True},
            )
            diffs = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diffs == []


def test_run_alembic_upgrade_creates_versioned_schema(tmp_path: Path) -> None:
    pytest.importorskip("alembic")
    from sqlalchemy import create_engine, inspect

    database_url = f"sqlite:///{tmp_path / 'startup-migrated.db'}"

    run_alembic_upgrade(database_url=database_url)
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
    finally:
        engine.dispose()

    assert "alembic_version" in table_names
    assert set(Base.metadata.tables).issubset(table_names)


def test_db_migration_status_reports_unversioned_database(tmp_path: Path) -> None:
    pytest.importorskip("alembic")
    database_url = f"sqlite:///{tmp_path / 'unversioned.db'}"

    status = db_migration_status(database_url=database_url)

    assert status["ok"] is True
    assert status["head_revision"] == "0003_add_llm_usage_records"
    assert status["current_revision"] is None
    assert status["version_table_present"] is False
    assert status["up_to_date"] is False


def test_db_migration_status_reports_stamped_database(tmp_path: Path) -> None:
    pytest.importorskip("alembic")
    from alembic import command

    database_url = f"sqlite:///{tmp_path / 'stamped.db'}"

    command.stamp(alembic_config(database_url=database_url), "head")
    status = db_migration_status(database_url=database_url)

    assert status["ok"] is True
    assert status["head_revision"] == "0003_add_llm_usage_records"
    assert status["current_revision"] == "0003_add_llm_usage_records"
    assert status["version_table_present"] is True
    assert status["up_to_date"] is True
