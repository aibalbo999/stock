from __future__ import annotations

import argparse
import json
import os

from app.services.system_backup import (
    SystemBackupService,
    backup_schedule_commands,
    decrypt_backup_archive,
    format_backup_result,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or dry-run restore a system backup.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a backup manifest and artifacts.")
    create_parser.add_argument("--destination", help="Backup directory. Defaults to backups/<timestamp>.")
    create_parser.add_argument("--dry-run", action="store_true", help="Preview backup operations.")
    create_parser.add_argument("--archive", action="store_true", help="Create a compressed .zip archive.")
    create_parser.add_argument(
        "--encrypt-passphrase-env",
        help="Read an encryption passphrase from this environment variable and encrypt the archive.",
    )
    create_parser.add_argument(
        "--archive-only",
        action="store_true",
        help="Remove the plain backup directory after creating the archive. Intended for encrypted archives.",
    )
    create_parser.add_argument("--keep", type=int, help="Keep only the newest N backup sets.")
    create_parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")

    restore_parser = subparsers.add_parser("restore", help="Dry-run or apply a backup restore.")
    restore_parser.add_argument("backup_dir", help="Backup directory containing manifest.json.")
    restore_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply restore operations. Omit this flag to run a dry-run only.",
    )
    restore_parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")

    decrypt_parser = subparsers.add_parser("decrypt", help="Decrypt an encrypted backup archive.")
    decrypt_parser.add_argument("encrypted_archive", help="Encrypted .zip.enc archive.")
    decrypt_parser.add_argument("--output", help="Output .zip path. Defaults to removing the .enc suffix.")
    decrypt_parser.add_argument(
        "--encrypt-passphrase-env",
        required=True,
        help="Environment variable containing the encryption passphrase.",
    )
    decrypt_parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")

    schedule_parser = subparsers.add_parser(
        "schedule-command",
        help="Print cron and launchd commands for daily encrypted backup scheduling.",
    )
    schedule_parser.add_argument("--time", default="02:30", help="Daily time in HH:MM.")
    schedule_parser.add_argument("--keep", type=int, default=14, help="Backup sets to retain.")
    schedule_parser.add_argument("--no-archive", action="store_true", help="Do not include --archive.")
    schedule_parser.add_argument(
        "--encrypt-passphrase-env",
        default="STOCK_AI_BACKUP_PASSPHRASE",
        help="Passphrase env var to include in the generated command. Empty disables encryption.",
    )
    schedule_parser.add_argument("--json", action="store_true", help="輸出 JSON，方便工具讀取。")

    args = parser.parse_args(argv)
    service = SystemBackupService()
    if args.command == "create":
        passphrase = _passphrase_from_env(args.encrypt_passphrase_env)
        if passphrase and not args.archive:
            parser.error("--encrypt-passphrase-env requires --archive")
        result = service.create_backup(
            destination=args.destination,
            dry_run=args.dry_run,
            archive=bool(args.archive),
            encrypt_passphrase=passphrase,
            archive_only=bool(args.archive_only),
            retention_count=args.keep,
        )
    elif args.command == "restore":
        result = service.restore_backup(args.backup_dir, dry_run=not args.apply)
    elif args.command == "decrypt":
        result = decrypt_backup_archive(
            args.encrypted_archive,
            passphrase=_required_passphrase_from_env(args.encrypt_passphrase_env),
            output_path=args.output,
        )
    else:
        env_name = str(args.encrypt_passphrase_env or "").strip() or None
        result = backup_schedule_commands(
            time_of_day=args.time,
            keep=args.keep,
            archive=not args.no_archive,
            encrypt_passphrase_env=env_name,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.command == "schedule-command":
        print("備份指令:")
        print(result["command"])
        print("")
        print("Cron:")
        print(result["cron"])
        print("")
        print("launchd:")
        print(json.dumps(result["launchd"], ensure_ascii=False, indent=2, sort_keys=True))
    elif args.command == "decrypt":
        print(f"Decrypted archive: {result['output_path']}")
    else:
        print(format_backup_result(result))
    return 1 if isinstance(result, dict) and result.get("status") in {"blocked"} else 0


def _passphrase_from_env(env_name: str | None) -> str | None:
    if not env_name:
        return None
    value = os.environ.get(env_name)
    if not value:
        raise SystemExit(f"Missing backup encryption passphrase env var: {env_name}")
    return value


def _required_passphrase_from_env(env_name: str) -> str:
    value = _passphrase_from_env(env_name)
    if not value:
        raise SystemExit(f"Missing backup encryption passphrase env var: {env_name}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
