from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.system_backup import (
    SystemBackupService,
    backup_schedule_commands,
    decrypt_backup_archive,
)


def _service(tmp_path, *, database_url: str, report_dir):
    return SystemBackupService(
        settings_provider=lambda: SimpleNamespace(
            database_url=database_url,
            report_dir=report_dir,
        ),
        now_func=lambda: datetime(2026, 6, 7, 8, 9, 10, tzinfo=timezone.utc),
    )


def test_system_backup_dry_run_describes_sqlite_and_reports(tmp_path) -> None:
    db_path = tmp_path / "stock_ai.db"
    db_path.write_bytes(b"sqlite")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "latest.md").write_text("report", encoding="utf-8")
    service = _service(tmp_path, database_url=f"sqlite:///{db_path}", report_dir=report_dir)

    result = service.create_backup(destination=tmp_path / "backup", dry_run=True)

    assert result["status"] == "dry_run"
    assert result["manifest"]["database"]["status"] == "ready"
    assert result["manifest"]["database"]["copy_supported"] is True
    assert result["manifest"]["reports"]["file_count"] == 1
    assert [operation["action"] for operation in result["operations"]] == [
        "write_manifest",
        "copy_database",
        "copy_reports",
    ]


def test_system_backup_create_writes_manifest_and_artifacts(tmp_path) -> None:
    db_path = tmp_path / "stock_ai.db"
    db_path.write_bytes(b"sqlite")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "latest.md").write_text("report", encoding="utf-8")
    service = _service(tmp_path, database_url=f"sqlite:///{db_path}", report_dir=report_dir)

    result = service.create_backup(destination=tmp_path / "backup")

    assert result["status"] == "created"
    assert (tmp_path / "backup" / "database.sqlite3").read_bytes() == b"sqlite"
    assert (tmp_path / "backup" / "reports" / "latest.md").read_text(encoding="utf-8") == "report"
    manifest = json.loads((tmp_path / "backup" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "stock_ai_backup_v1"
    assert manifest["reports"]["artifacts"] == ["latest.md"]


def test_system_backup_restore_defaults_to_dry_run(tmp_path) -> None:
    db_path = tmp_path / "stock_ai.db"
    db_path.write_bytes(b"current")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    service = _service(tmp_path, database_url=f"sqlite:///{db_path}", report_dir=report_dir)
    service.create_backup(destination=tmp_path / "backup")

    result = service.restore_backup(tmp_path / "backup")

    assert result["status"] == "dry_run"
    assert result["validation"]["valid"] is True
    assert result["operations"][0]["action"] == "restore_sqlite_database"
    assert db_path.read_bytes() == b"current"


def test_system_backup_reports_external_database_dump_requirement(tmp_path) -> None:
    service = _service(
        tmp_path,
        database_url="postgresql+psycopg://user:secret@localhost:5432/stock_ai",
        report_dir=tmp_path / "missing_reports",
    )

    result = service.create_backup(destination=tmp_path / "backup", dry_run=True)

    assert result["status"] == "dry_run"
    assert result["manifest"]["database"]["status"] == "external_dump_required"
    assert "secret" not in result["manifest"]["database"]["url"]
    assert result["operations"][1]["action"] == "database_external_dump_required"


def test_system_backup_create_encrypted_archive_only_and_decrypts(tmp_path) -> None:
    db_path = tmp_path / "stock_ai.db"
    db_path.write_bytes(b"sqlite")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "latest.md").write_text("report", encoding="utf-8")
    service = _service(tmp_path, database_url=f"sqlite:///{db_path}", report_dir=report_dir)

    result = service.create_backup(
        destination=tmp_path / "backup",
        archive=True,
        encrypt_passphrase="secret passphrase",
        archive_only=True,
    )

    assert result["status"] == "created"
    assert result["archive_only"] is True
    assert result["manifest_path"] is None
    assert not (tmp_path / "backup").exists()
    encrypted_path = tmp_path / "backup.zip.enc"
    assert result["encrypted_archive_path"] == str(encrypted_path)
    assert encrypted_path.exists()
    decrypted = decrypt_backup_archive(
        encrypted_path,
        passphrase="secret passphrase",
        output_path=tmp_path / "decrypted.zip",
    )
    assert decrypted["status"] == "decrypted"
    with zipfile.ZipFile(tmp_path / "decrypted.zip") as archive:
        assert sorted(archive.namelist()) == [
            "database.sqlite3",
            "manifest.json",
            "reports/latest.md",
        ]
        assert archive.read("reports/latest.md") == b"report"


def test_system_backup_retention_keeps_newest_backup_sets(tmp_path) -> None:
    db_path = tmp_path / "stock_ai.db"
    db_path.write_bytes(b"sqlite")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    service = _service(tmp_path, database_url=f"sqlite:///{db_path}", report_dir=report_dir)
    old_one = tmp_path / "stock_ai_backup_20260601_000000"
    old_two = tmp_path / "stock_ai_backup_20260602_000000.zip.enc"
    old_one.mkdir()
    old_two.write_text("old", encoding="utf-8")

    result = service.create_backup(destination=tmp_path / "stock_ai_backup_20260607_080910", retention_count=1)

    assert result["retention"]["enabled"] is True
    assert not old_one.exists()
    assert not old_two.exists()
    assert (tmp_path / "stock_ai_backup_20260607_080910").exists()


def test_backup_schedule_commands_include_encrypted_archive_retention(tmp_path) -> None:
    result = backup_schedule_commands(
        cwd=tmp_path,
        time_of_day="03:45",
        keep=21,
        encrypt_passphrase_env="BACKUP_SECRET",
    )

    assert "--archive" in result["command"]
    assert "--archive-only" in result["command"]
    assert "--keep 21" in result["command"]
    assert "--encrypt-passphrase-env BACKUP_SECRET" in result["command"]
    assert result["cron"].startswith("45 3 * * *")
    assert result["launchd"]["start_calendar_interval"] == {"Hour": 3, "Minute": 45}
