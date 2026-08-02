"""Backup CLI (spec 99 §5) — the path that works when Radd does not.

The real disaster is a fresh deployment with an empty database: no app running
to click a button in, and no admin account to log in with. This runs the same
service functions with no HTTP layer, no plugin registry and no maintenance mode
(nothing is serving to pause).

    uv run python -m radd.backup list
    uv run python -m radd.backup create [--no-attachments]
    uv run python -m radd.backup verify  <name>
    uv run python -m radd.backup restore <name> [--yes] [--force-schema]
    uv run python -m radd.backup status
"""

import argparse
import asyncio
import sys
from datetime import datetime

from radd.config import settings

from . import postgres, service, store
from .types import BackupKind, RunStage


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _progress(stage: RunStage) -> None:
    print(f"  … {stage.value}", flush=True)


async def _cmd_status() -> int:
    directory = store.directory_status()
    tools = await postgres.tool_status()
    print(f"directory   {directory.path}")
    print(f"            {'writable' if directory.writable else 'NOT WRITABLE'}", end="")
    print(f", {_human(directory.free_bytes)} free" if directory.free_bytes is not None else "")
    if directory.problem:
        print(f"            {directory.problem}")
    print(f"pg_dump     {tools.pg_dump.version or 'NOT FOUND'} ({tools.pg_dump.path or '-'})")
    print(f"pg_restore  {tools.pg_restore.version or 'NOT FOUND'} ({tools.pg_restore.path or '-'})")
    if tools.problem:
        print(f"            {tools.problem}")
    if settings.backup_encryption:
        try:
            print(f"encryption  aes-256-gcm, key {service.active_key().key_id} ({settings.backup_key_file})")
        except Exception as exc:  # noqa: BLE001
            print(f"encryption  KEY PROBLEM: {exc}")
    else:
        print("encryption  DISABLED (RADD_BACKUP_ENCRYPTION=false)")
    return 0 if directory.writable and tools.available else 1


async def _cmd_list() -> int:
    backups = store.listing()
    if not backups:
        print(f"no backups in {settings.backup_dir}")
        return 0
    print(f"{'NAME':<40} {'TAKEN':<20} {'SIZE':>10}  KIND       STATUS")
    for item in backups:
        verdict = service.compatibility(item.manifest)
        status = "ok" if item.complete and verdict.restorable else (item.problem or verdict.reason or "")
        taken = item.created_at.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{item.name:<40} {taken:<20} {_human(item.size_bytes):>10}  {item.kind:<10} {status}")
    return 0


async def _cmd_create(no_attachments: bool) -> int:
    print("creating backup…")
    result = await service.create_backup(
        kind=BackupKind.MANUAL,
        include_attachments=False if no_attachments else None,
        created_by="cli",
        on_stage=_progress,
    )
    print(f"created {result.name} ({_human(result.size_bytes)}), verified")
    return 0


async def _cmd_verify(name: str) -> int:
    entries = await service.verify(name)
    print(f"{name}: readable, {entries} entries in the dump")
    return 0


async def _cmd_restore(name: str, assume_yes: bool, force_schema: bool) -> int:
    stored = store.load(name)
    if stored.manifest is None:
        print(f"{name}: {stored.problem}", file=sys.stderr)
        return 1
    taken = stored.created_at.strftime("%Y-%m-%d %H:%M:%S")
    print(f"about to REPLACE every row in {postgres.database_name()} with {name}")
    print(f"  taken       {taken} by {stored.manifest.created_by or 'unknown'}")
    print(f"  schema      v{stored.manifest.schema_version} (alembic {stored.manifest.alembic_revision})")
    print(f"  attachments {'included' if stored.manifest.includes_attachments else 'not included'}")
    if not assume_yes:
        if input("type the database name to confirm: ").strip() != postgres.database_name():
            print("aborted", file=sys.stderr)
            return 1
    await service.restore_backup(
        name, override_compatibility=force_schema, on_stage=_progress
    )
    print(f"restored {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m radd.backup", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="directory, tools and key")
    sub.add_parser("list", help="artifacts on disk, newest first")
    create = sub.add_parser("create", help="take a backup now")
    create.add_argument("--no-attachments", action="store_true")
    verify = sub.add_parser("verify", help="prove an artifact is readable")
    verify.add_argument("name")
    restore = sub.add_parser("restore", help="REPLACE this instance's data")
    restore.add_argument("name")
    restore.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    restore.add_argument(
        "--force-schema", action="store_true", help="restore across a breaking schema change"
    )
    args = parser.parse_args(argv)

    match args.command:
        case "status":
            coroutine = _cmd_status()
        case "list":
            coroutine = _cmd_list()
        case "create":
            coroutine = _cmd_create(args.no_attachments)
        case "verify":
            coroutine = _cmd_verify(args.name)
        case _:
            coroutine = _cmd_restore(args.name, args.yes, args.force_schema)

    try:
        return asyncio.run(coroutine)
    except service.BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
