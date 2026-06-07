from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.status import _redact_database_url


DEFAULT_BACKUP_ROOT = Path("backups")
MANIFEST_NAME = "manifest.json"


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
    ) -> dict:
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
        operations = _backup_operations(backup_dir, database_plan, report_plan)
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
        return {
            "status": "created",
            "backup_dir": str(backup_dir),
            "manifest_path": str(manifest_path),
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


def _backup_operations(backup_dir: Path, database_plan: dict, report_plan: dict) -> list[dict]:
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
    return operations


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
