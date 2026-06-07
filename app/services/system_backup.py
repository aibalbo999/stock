from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.status import _redact_database_url


DEFAULT_BACKUP_ROOT = Path("backups")
MANIFEST_NAME = "manifest.json"
ENCRYPTED_BACKUP_FORMAT = "stock_ai_encrypted_backup_v1"
ENCRYPTION_KDF_ITERATIONS = 390_000


class SystemBackupService:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any] = get_settings,
        now_func: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings_provider = settings_provider
        self.now_func = now_func or (lambda: datetime.now(timezone.utc))

    def create_backup(
        self,
        *,
        destination: str | Path | None = None,
        dry_run: bool = False,
        archive: bool = False,
        encrypt_passphrase: str | None = None,
        archive_only: bool = False,
        retention_count: int | None = None,
    ) -> dict:
        if archive_only and not archive:
            raise ValueError("archive_only requires archive=True")
        settings = self.settings_provider()
        backup_dir = Path(destination) if destination else self._default_backup_dir()
        database_plan = _database_backup_plan(str(getattr(settings, "database_url", "") or ""))
        report_plan = _report_backup_plan(Path(getattr(settings, "report_dir", Path("reports"))))
        manifest = {
            "format": "stock_ai_backup_v1",
            "created_at": self.now_func().isoformat(),
            "backup_dir": str(backup_dir),
            "database": database_plan,
            "reports": report_plan,
        }
        operations = _backup_operations(
            backup_dir,
            database_plan,
            report_plan,
            archive=archive,
            encrypt=bool(encrypt_passphrase),
            archive_only=archive_only,
            retention_count=retention_count,
        )
        if dry_run:
            return {
                "status": "dry_run",
                "backup_dir": str(backup_dir),
                "manifest": manifest,
                "operations": operations,
            }

        backup_dir.mkdir(parents=True, exist_ok=False)
        database_artifact = _copy_database_artifact(backup_dir, database_plan)
        report_artifacts = _copy_report_artifacts(backup_dir, report_plan)
        manifest["database"]["artifact"] = database_artifact
        manifest["reports"]["artifacts"] = report_artifacts
        manifest_path = backup_dir / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        archive_path = None
        encrypted_archive_path = None
        if archive:
            archive_path = _create_backup_archive(backup_dir)
            if encrypt_passphrase:
                encrypted_archive_path = _encrypt_file(archive_path, encrypt_passphrase)
                archive_path.unlink()
            if archive_only:
                shutil.rmtree(backup_dir)
        retention = _apply_backup_retention(
            backup_dir.parent,
            keep=retention_count,
            preserve_paths=[
                path
                for path in [backup_dir, archive_path, encrypted_archive_path]
                if path is not None
            ],
            dry_run=False,
        )
        return {
            "status": "created",
            "backup_dir": str(backup_dir),
            "manifest_path": str(manifest_path) if manifest_path.exists() else None,
            "archive_path": str(archive_path) if archive_path and archive_path.exists() else None,
            "encrypted_archive_path": str(encrypted_archive_path) if encrypted_archive_path else None,
            "archive_only": bool(archive_only),
            "retention": retention,
            "manifest": manifest,
            "operations": operations,
        }

    def restore_backup(
        self,
        backup_dir: str | Path,
        *,
        dry_run: bool = True,
    ) -> dict:
        settings = self.settings_provider()
        backup_path = Path(backup_dir)
        manifest_path = backup_path / MANIFEST_NAME
        if not manifest_path.exists():
            raise FileNotFoundError(f"Backup manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        current_database = _database_backup_plan(str(getattr(settings, "database_url", "") or ""))
        current_reports = _report_backup_plan(Path(getattr(settings, "report_dir", Path("reports"))))
        validation = _validate_backup_manifest(backup_path, manifest)
        operations = _restore_operations(
            backup_path,
            manifest,
            current_database=current_database,
            current_reports=current_reports,
        )
        if dry_run:
            return {
                "status": "dry_run",
                "backup_dir": str(backup_path),
                "manifest": manifest,
                "validation": validation,
                "operations": operations,
            }
        if not validation["valid"]:
            return {
                "status": "blocked",
                "backup_dir": str(backup_path),
                "manifest": manifest,
                "validation": validation,
                "operations": operations,
            }
        applied = _apply_restore_operations(operations)
        return {
            "status": "restored",
            "backup_dir": str(backup_path),
            "manifest": manifest,
            "validation": validation,
            "operations": operations,
            "applied": applied,
        }

    def _default_backup_dir(self) -> Path:
        timestamp = self.now_func().strftime("%Y%m%d_%H%M%S")
        return DEFAULT_BACKUP_ROOT / f"stock_ai_backup_{timestamp}"


def decrypt_backup_archive(
    encrypted_path: str | Path,
    *,
    passphrase: str,
    output_path: str | Path | None = None,
) -> dict:
    source_path = Path(encrypted_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if payload.get("format") != ENCRYPTED_BACKUP_FORMAT:
        raise ValueError("Unsupported encrypted backup format")
    target_path = Path(output_path) if output_path else source_path.with_suffix("")
    token = str(payload.get("payload") or "").encode("utf-8")
    salt = bytes.fromhex(str(payload.get("salt_hex") or ""))
    key = _derive_fernet_key(passphrase, salt=salt)
    target_path.write_bytes(Fernet(key).decrypt(token))
    return {
        "status": "decrypted",
        "source": str(source_path),
        "output_path": str(target_path),
        "format": payload.get("format"),
    }


def backup_schedule_commands(
    *,
    cwd: str | Path = ".",
    time_of_day: str = "02:30",
    keep: int = 14,
    archive: bool = True,
    encrypt_passphrase_env: str | None = "STOCK_AI_BACKUP_PASSPHRASE",
) -> dict:
    safe_time = str(time_of_day or "02:30")
    hour, minute = _parse_backup_time(safe_time)
    command_parts = [
        ".venv/bin/python",
        "scripts/system_backup.py",
        "create",
        "--keep",
        str(max(1, int(keep or 14))),
    ]
    if archive:
        command_parts.append("--archive")
    if encrypt_passphrase_env:
        command_parts.extend(["--encrypt-passphrase-env", str(encrypt_passphrase_env)])
        command_parts.append("--archive-only")
    command = " ".join(command_parts)
    workdir = str(Path(cwd).resolve())
    return {
        "command": command,
        "cron": f"{minute} {hour} * * * cd {workdir} && {command} >> logs/system_backup.log 2>&1",
        "launchd": {
            "label": "com.stock-ai.system-backup",
            "program_arguments": ["/bin/zsh", "-lc", f"cd {workdir} && {command}"],
            "start_calendar_interval": {"Hour": hour, "Minute": minute},
            "standard_out_path": str(Path(workdir) / "logs" / "system_backup.log"),
            "standard_error_path": str(Path(workdir) / "logs" / "system_backup.err.log"),
        },
    }


def format_backup_result(result: dict) -> str:
    lines = [
        f"System backup: {result['status']}",
        f"Backup dir: {result['backup_dir']}",
    ]
    validation = result.get("validation")
    if validation:
        lines.append(
            "Validation: "
            + ("valid" if validation.get("valid") else "invalid")
            + f" ({len(validation.get('missing_files') or [])} missing files)"
        )
    for operation in result.get("operations") or []:
        marker = "DRY" if result["status"] == "dry_run" else "DO"
        lines.append(f"- [{marker}] {operation['action']}: {operation['description']}")
    if result.get("archive_path"):
        lines.append(f"Archive: {result['archive_path']}")
    if result.get("encrypted_archive_path"):
        lines.append(f"Encrypted archive: {result['encrypted_archive_path']}")
    retention = result.get("retention") or {}
    if retention.get("deleted"):
        lines.append("Retention deleted: " + ", ".join(retention["deleted"]))
    return "\n".join(lines)


def _database_backup_plan(database_url: str) -> dict:
    redacted_url = _redact_database_url(database_url)
    try:
        url = make_url(database_url)
    except Exception as exc:
        return {
            "engine": "unknown",
            "url": redacted_url,
            "copy_supported": False,
            "status": "invalid_database_url",
            "error": str(exc),
        }
    engine = url.get_backend_name()
    if engine == "sqlite":
        database = url.database or ""
        if not database or database == ":memory:":
            return {
                "engine": engine,
                "url": redacted_url,
                "copy_supported": False,
                "status": "sqlite_memory_database_not_backupable",
            }
        source_path = Path(database).expanduser()
        if not source_path.is_absolute():
            source_path = source_path.resolve()
        return {
            "engine": engine,
            "url": redacted_url,
            "copy_supported": source_path.exists(),
            "status": "ready" if source_path.exists() else "source_missing",
            "source_path": str(source_path),
            "artifact": "database.sqlite3",
            "size_bytes": source_path.stat().st_size if source_path.exists() else 0,
        }
    return {
        "engine": engine,
        "url": redacted_url,
        "copy_supported": False,
        "status": "external_dump_required",
        "recommended_command": (
            "Use the deployment database tool, for example: "
            "pg_dump --format=custom --file <backup_dir>/database.dump \"$DATABASE_URL\""
        ),
    }


def _report_backup_plan(report_dir: Path) -> dict:
    source_dir = report_dir.expanduser()
    if not source_dir.is_absolute():
        source_dir = source_dir.resolve()
    files = []
    if source_dir.exists():
        files = [
            {
                "path": str(path.relative_to(source_dir)),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(source_dir.rglob("*"))
            if path.is_file()
        ]
    return {
        "source_dir": str(source_dir),
        "exists": source_dir.exists(),
        "file_count": len(files),
        "files": files,
        "artifact_dir": "reports",
    }


def _backup_operations(
    backup_dir: Path,
    database_plan: dict,
    report_plan: dict,
    *,
    archive: bool = False,
    encrypt: bool = False,
    archive_only: bool = False,
    retention_count: int | None = None,
) -> list[dict]:
    operations = [
        {
            "action": "write_manifest",
            "description": f"Write backup manifest to {backup_dir / MANIFEST_NAME}",
        }
    ]
    if database_plan.get("copy_supported"):
        operations.append(
            {
                "action": "copy_database",
                "description": (
                    f"Copy SQLite database {database_plan['source_path']} "
                    f"to {backup_dir / database_plan['artifact']}"
                ),
            }
        )
    else:
        operations.append(
            {
                "action": "database_external_dump_required",
                "description": str(
                    database_plan.get("recommended_command")
                    or database_plan.get("status")
                    or "Database copy is not available."
                ),
            }
        )
    if report_plan.get("file_count"):
        operations.append(
            {
                "action": "copy_reports",
                "description": (
                    f"Copy {report_plan['file_count']} report files "
                    f"from {report_plan['source_dir']}"
                ),
            }
        )
    else:
        operations.append(
            {
                "action": "skip_reports",
                "description": f"No report files found in {report_plan['source_dir']}",
            }
        )
    if archive:
        operations.append(
            {
                "action": "create_archive",
                "description": f"Create compressed archive {backup_dir.with_suffix('.zip')}",
            }
        )
    if encrypt:
        operations.append(
            {
                "action": "encrypt_archive",
                "description": "Encrypt archive with Fernet/PBKDF2 using passphrase from environment.",
            }
        )
    if archive_only:
        operations.append(
            {
                "action": "remove_plain_backup_dir",
                "description": "Remove the unencrypted backup directory after archive creation.",
            }
        )
    if retention_count is not None:
        operations.append(
            {
                "action": "apply_retention",
                "description": f"Keep the newest {max(1, int(retention_count))} backup sets.",
            }
        )
    return operations


def _create_backup_archive(backup_dir: Path) -> Path:
    archive_path = backup_dir.with_suffix(".zip")
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive_file:
        for path in sorted(backup_dir.rglob("*")):
            if path.is_file():
                archive_file.write(path, path.relative_to(backup_dir))
    return archive_path


def _encrypt_file(path: Path, passphrase: str) -> Path:
    if not passphrase:
        raise ValueError("Backup encryption passphrase is empty")
    salt = os.urandom(16)
    key = _derive_fernet_key(passphrase, salt=salt)
    encrypted = Fernet(key).encrypt(path.read_bytes())
    payload = {
        "format": ENCRYPTED_BACKUP_FORMAT,
        "kdf": "PBKDF2HMAC-SHA256",
        "iterations": ENCRYPTION_KDF_ITERATIONS,
        "salt_hex": salt.hex(),
        "payload": encrypted.decode("utf-8"),
    }
    encrypted_path = path.with_suffix(path.suffix + ".enc")
    encrypted_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return encrypted_path


def _derive_fernet_key(passphrase: str, *, salt: bytes) -> bytes:
    import base64

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ENCRYPTION_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _apply_backup_retention(
    backup_root: Path,
    *,
    keep: int | None,
    preserve_paths: list[Path],
    dry_run: bool,
) -> dict:
    if keep is None:
        return {"enabled": False, "deleted": [], "planned_delete": []}
    safe_keep = max(1, int(keep))
    preserve = {path.resolve() for path in preserve_paths if path.exists()}
    candidates = [
        path
        for path in backup_root.glob("stock_ai_backup_*")
        if path.resolve() not in preserve
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    to_delete = candidates[max(0, safe_keep - len(preserve)) :]
    deleted = []
    for path in to_delete:
        if dry_run:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        deleted.append(str(path))
    return {
        "enabled": True,
        "keep": safe_keep,
        "deleted": deleted,
        "planned_delete": [str(path) for path in to_delete],
    }


def _parse_backup_time(value: str) -> tuple[int, int]:
    hour_text, minute_text = str(value).split(":", 1)
    hour = max(0, min(23, int(hour_text)))
    minute = max(0, min(59, int(minute_text)))
    return hour, minute


def _copy_database_artifact(backup_dir: Path, database_plan: dict) -> str | None:
    if not database_plan.get("copy_supported"):
        return None
    artifact = str(database_plan.get("artifact") or "database.sqlite3")
    shutil.copy2(Path(database_plan["source_path"]), backup_dir / artifact)
    return artifact


def _copy_report_artifacts(backup_dir: Path, report_plan: dict) -> list[str]:
    artifacts: list[str] = []
    if not report_plan.get("file_count"):
        return artifacts
    source_dir = Path(report_plan["source_dir"])
    target_dir = backup_dir / str(report_plan.get("artifact_dir") or "reports")
    for row in report_plan.get("files") or []:
        relative_path = Path(str(row["path"]))
        source_path = source_dir / relative_path
        target_path = target_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        artifacts.append(str(relative_path))
    return artifacts


def _validate_backup_manifest(backup_dir: Path, manifest: dict) -> dict:
    missing_files = []
    database = manifest.get("database") if isinstance(manifest.get("database"), dict) else {}
    database_artifact = database.get("artifact")
    if database_artifact and not (backup_dir / str(database_artifact)).exists():
        missing_files.append(str(database_artifact))
    reports = manifest.get("reports") if isinstance(manifest.get("reports"), dict) else {}
    for artifact in reports.get("artifacts") or []:
        artifact_path = backup_dir / str(reports.get("artifact_dir") or "reports") / str(artifact)
        if not artifact_path.exists():
            missing_files.append(str(artifact_path.relative_to(backup_dir)))
    return {
        "format": manifest.get("format"),
        "valid": manifest.get("format") == "stock_ai_backup_v1" and not missing_files,
        "missing_files": missing_files,
    }


def _restore_operations(
    backup_dir: Path,
    manifest: dict,
    *,
    current_database: dict,
    current_reports: dict,
) -> list[dict]:
    operations: list[dict] = []
    database = manifest.get("database") if isinstance(manifest.get("database"), dict) else {}
    database_artifact = database.get("artifact")
    if database_artifact and current_database.get("engine") == "sqlite":
        target_path = current_database.get("source_path")
        operations.append(
            {
                "action": "restore_sqlite_database",
                "source": str(backup_dir / str(database_artifact)),
                "target": target_path,
                "description": f"Restore SQLite database to {target_path}",
            }
        )
    elif database.get("status") == "external_dump_required":
        operations.append(
            {
                "action": "restore_external_database_manually",
                "description": "Use the matching database restore tool for the external dump.",
            }
        )
    reports = manifest.get("reports") if isinstance(manifest.get("reports"), dict) else {}
    artifacts = reports.get("artifacts") or []
    if artifacts:
        operations.append(
            {
                "action": "restore_reports",
                "source": str(backup_dir / str(reports.get("artifact_dir") or "reports")),
                "target": current_reports.get("source_dir"),
                "file_count": len(artifacts),
                "description": (
                    f"Restore {len(artifacts)} report files to {current_reports.get('source_dir')}"
                ),
            }
        )
    return operations


def _apply_restore_operations(operations: list[dict]) -> list[dict]:
    applied = []
    for operation in operations:
        action = operation.get("action")
        if action == "restore_sqlite_database":
            source = Path(str(operation["source"]))
            target = Path(str(operation["target"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                pre_restore = target.with_suffix(target.suffix + ".pre_restore")
                shutil.copy2(target, pre_restore)
                operation["pre_restore_copy"] = str(pre_restore)
            shutil.copy2(source, target)
            applied.append(operation)
        elif action == "restore_reports":
            source_dir = Path(str(operation["source"]))
            target_dir = Path(str(operation["target"]))
            target_dir.mkdir(parents=True, exist_ok=True)
            for source_path in source_dir.rglob("*"):
                if not source_path.is_file():
                    continue
                relative = source_path.relative_to(source_dir)
                target_path = target_dir / relative
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
            applied.append(operation)
    return applied
