from __future__ import annotations

import argparse
import json

from app.services.system_backup import SystemBackupService, format_backup_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or dry-run restore a system backup.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a backup manifest and artifacts.")
    create_parser.add_argument("--destination", help="Backup directory. Defaults to backups/<timestamp>.")
    create_parser.add_argument("--dry-run", action="store_true", help="Preview backup operations.")
    create_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    restore_parser = subparsers.add_parser("restore", help="Dry-run or apply a backup restore.")
    restore_parser.add_argument("backup_dir", help="Backup directory containing manifest.json.")
    restore_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply restore operations. Omit this flag to run a dry-run only.",
    )
    restore_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    args = parser.parse_args(argv)
    service = SystemBackupService()
    if args.command == "create":
        result = service.create_backup(destination=args.destination, dry_run=args.dry_run)
    else:
        result = service.restore_backup(args.backup_dir, dry_run=not args.apply)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_backup_result(result))
    return 1 if result["status"] in {"blocked"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
