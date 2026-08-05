"""Creating and restoring backups (spec 99 §§4-5).

No FastAPI, no plugin imports, no ORM models — the CLI calls exactly these
functions to restore an EMPTY database, where no plugin registry could load.
`modules/backup/` wraps them for the API; neither owns anything the other needs.

Progress is reported through an optional `on_stage` callback so the HTTP layer
can write it to a run row while the CLI just prints it.
"""

import asyncio
import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from radd.config import settings
from radd.schema_version import SCHEMA_CHANGELOG, SCHEMA_VERSION

from . import artifact as art, crypto, postgres, store
from .artifact import Manifest
from .crypto import BackupKey, BackupKeyError
from .errors import BackupError
from .store import StoredBackup
from .types import BackupKind, RunStage

logger = logging.getLogger(__name__)

OnStage = Callable[[RunStage], None] | None


def _stage(on_stage: OnStage, stage: RunStage) -> None:
    if on_stage is not None:
        on_stage(stage)


def _radd_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("radd-server")
    except PackageNotFoundError:
        return "0.0.0"


async def _alembic_revision() -> str | None:
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    from radd.db import engine

    async with engine.connect() as connection:
        try:
            return str((await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one())
        except ProgrammingError:  # an empty database has no such table (RADD-898:
            # the broad catch also read "connection refused" as "no version")
            return None


def active_key() -> BackupKey | None:
    """The key new artifacts are sealed with, or None when encryption is off."""
    if not settings.backup_encryption:
        return None
    return crypto.load_key()


def key_for(manifest: Manifest) -> BackupKey | None:
    """The key an existing artifact needs, checked against what we hold."""
    if not manifest.encrypted:
        return None
    key = crypto.load_key(create=False)
    if manifest.key_id and key.key_id != manifest.key_id:
        raise BackupKeyError(
            f"this artifact was encrypted with key {manifest.key_id}, but the key "
            f"at {settings.backup_key_file} is {key.key_id} — restore it with the "
            f"original key file"
        )
    return key


# --- create ---


@dataclass(frozen=True)
class BackupResult:
    name: str
    size_bytes: int
    manifest: Manifest


async def create_backup(
    *,
    kind: BackupKind = BackupKind.MANUAL,
    include_attachments: bool | None = None,
    created_by: str | None = None,
    schedule_id: str | None = None,
    on_stage: OnStage = None,
) -> BackupResult:
    """Dump, pack, seal, verify. Returns once the artifact is proven readable."""
    status = await postgres.tool_status()
    if not status.available:
        raise BackupError(status.problem or "backup tools unavailable")

    directory = store.directory_status()
    if not directory.writable:
        raise BackupError(directory.problem or f"{directory.path} is not writable")

    existing = store.listing()
    needed = store.estimated_size(existing, await postgres.database_bytes())
    if directory.free_bytes is not None and directory.free_bytes < needed + settings.backup_min_free_bytes:
        raise BackupError(
            f"not enough free space in {directory.path}: {directory.free_bytes:,} bytes free, "
            f"~{needed:,} needed plus {settings.backup_min_free_bytes:,} reserved"
        )

    attachments = _attachments_dir(include_attachments)
    key = active_key()
    manifest = art.build_manifest(
        kind=kind,
        radd_version=_radd_version(),
        schema_version=SCHEMA_VERSION,
        alembic_revision=await _alembic_revision(),
        pg_server_version=await postgres.server_version(),
        includes_attachments=attachments is not None,
        key=key,
        created_by=created_by,
        schedule_id=schedule_id,
    )

    name = art.new_artifact_name()
    target = store.ensure_dir() / name
    with tempfile.TemporaryDirectory(prefix="radd-backup-") as scratch:
        dump_path = Path(scratch) / art.DUMP_MEMBER
        _stage(on_stage, RunStage.DUMPING)
        await postgres.dump_to(dump_path)

        _stage(on_stage, RunStage.PACKING)
        try:
            await asyncio.to_thread(_pack, target, manifest, key, dump_path, attachments)
        except Exception:
            target.unlink(missing_ok=True)  # never leave a half-written artifact
            raise

        _stage(on_stage, RunStage.VERIFYING)
        await verify(name, scratch=scratch)

    result = store.load(name)
    return BackupResult(name, result.size_bytes, manifest)


def _attachments_dir(include: bool | None) -> Path | None:
    """The attachments tree to include, or None.

    Keys off the DEFAULT storage host (spec 102): filesystem default -> its
    root; s3 default -> None, because an object store has its own lifecycle and
    copying a bucket through this process is the wrong plumbing. Additional
    filesystem hosts are a documented gap until the per-host packing lands
    (docs/deploy.md)."""
    from radd.modules.attachments import hosts as storage_hosts
    from radd.modules.attachments.types import StorageHostType

    default = storage_hosts.default_snapshot()
    if default.get("type") != StorageHostType.FILESYSTEM.value:
        return None
    wanted = settings.backup_include_attachments_default if include is None else include
    if not wanted:
        return None
    path = Path(default.get("root_dir") or settings.attachments_dir)
    return path if path.is_dir() else None


def _pack(
    target: Path, manifest: Manifest, key: BackupKey | None, dump_path: Path, attachments: Path | None
) -> None:
    """Blocking: tar + seal. Runs in a thread (the sealer is CPU-bound)."""
    with art.write_artifact(target, manifest, key=key) as tar:
        tar.add(dump_path, arcname=art.DUMP_MEMBER)
        if attachments is not None:
            tar.add(attachments, arcname=art.ATTACHMENTS_MEMBER)


# --- verify ---


async def verify(name: str, *, scratch: str | None = None) -> int:
    """Prove an artifact is readable: open it, extract the dump, `pg_restore --list`.

    Every finished backup goes through this, so "verified" on the backups page is
    a fact. Returns the number of entries in the dump's table of contents.
    """
    stored = store.load(name)
    if stored.manifest is None:
        raise BackupError(stored.problem or "unreadable artifact")
    if not stored.complete:
        raise BackupError("artifact has no footer — the backup did not finish")
    key = key_for(stored.manifest)

    with tempfile.TemporaryDirectory(prefix="radd-verify-", dir=scratch) as workspace:
        dump_path = Path(workspace) / art.DUMP_MEMBER
        await asyncio.to_thread(_extract_dump, stored, key, dump_path)
        return await postgres.list_dump(dump_path)


def _extract_dump(stored: StoredBackup, key: BackupKey | None, target: Path) -> None:
    assert stored.manifest is not None
    with art.read_artifact(stored.path, stored.manifest, key=key) as tar:
        for member in tar:
            if member.name == art.DUMP_MEMBER:
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise BackupError("artifact contains no database dump")
                with target.open("wb") as handle:
                    shutil.copyfileobj(extracted, handle)
                return
    raise BackupError(f"artifact contains no {art.DUMP_MEMBER}")


# --- compatibility ---


@dataclass(frozen=True)
class Compatibility:
    restorable: bool
    reason: str | None
    needs_override: bool = False


def compatibility(manifest: Manifest | None) -> Compatibility:
    """Can this build restore this artifact? (spec 99 §2)

    `schema_version` is bumped only when older data can no longer be made correct
    by `alembic upgrade head` alone, so newer is a hard refusal (this build cannot
    read data from a future one) and older-across-a-bump needs an explicit
    override, with the changelog line saying what it will cost.
    """
    if manifest is None:
        return Compatibility(False, "unreadable artifact header")
    if manifest.schema_version > SCHEMA_VERSION:
        return Compatibility(
            False,
            f"the backup is from a newer Radd (schema v{manifest.schema_version}; "
            f"this build reads v{SCHEMA_VERSION}) — upgrade before restoring",
        )
    crossed = [
        version
        for version in range(manifest.schema_version + 1, SCHEMA_VERSION + 1)
        if version in SCHEMA_CHANGELOG
    ]
    if crossed:
        notes = "; ".join(f"v{version}: {SCHEMA_CHANGELOG[version]}" for version in crossed)
        return Compatibility(
            False,
            f"restoring across a breaking schema change ({notes})",
            needs_override=True,
        )
    return Compatibility(True, None)


# --- restore ---


async def restore_backup(
    name: str,
    *,
    override_compatibility: bool = False,
    skip_safety_backup: bool = False,
    on_stage: OnStage = None,
) -> None:
    """Replace this instance's data with an artifact's. See spec 99 §4.

    The caller is responsible for entering maintenance mode (the API layer does;
    the CLI has nothing to pause). On failure after the schema is dropped, the
    safety backup is restored automatically — and if THAT fails the exception
    propagates with maintenance still engaged, because a half-restored Radd must
    not serve traffic.
    """
    stored = store.load(name)
    if stored.manifest is None:
        raise BackupError(stored.problem or "unreadable artifact")
    if not stored.complete:
        raise BackupError("artifact has no footer — the backup did not finish")

    verdict = compatibility(stored.manifest)
    if not verdict.restorable and not (verdict.needs_override and override_compatibility):
        raise BackupError(verdict.reason or "incompatible backup")
    key = key_for(stored.manifest)  # raises before anything is touched

    safety: BackupResult | None = None
    if not skip_safety_backup:
        _stage(on_stage, RunStage.SAFETY_BACKUP)
        safety = await create_backup(kind=BackupKind.PRE_RESTORE, created_by="restore")

    with tempfile.TemporaryDirectory(prefix="radd-restore-") as workspace:
        dump_path = Path(workspace) / art.DUMP_MEMBER
        attachments_root = Path(workspace) / art.ATTACHMENTS_MEMBER
        await asyncio.to_thread(_unpack, stored, key, dump_path, attachments_root)

        _stage(on_stage, RunStage.DRAINING)
        await postgres.terminate_other_backends()

        _stage(on_stage, RunStage.RESTORING)
        try:
            await postgres.drop_public_schema()
            await postgres.restore_from(dump_path)
        except Exception as exc:
            if safety is None:
                raise
            logger.exception("restore failed; rolling back to the safety backup")
            await _roll_back(safety)
            raise BackupError(
                f"restore failed and was rolled back to {safety.name}: {exc}"
            ) from exc

        # The pool's connections were opened against a schema that no longer
        # exists; cached plans and type OIDs are both stale.
        await postgres.dispose_pool()

        _stage(on_stage, RunStage.MIGRATING)
        await asyncio.to_thread(upgrade_to_head)

        if attachments_root.is_dir():
            _stage(on_stage, RunStage.ATTACHMENTS)
            # Extract OVER the existing tree: a file present now but absent from
            # the backup is left alone. Orphaned blobs are harmless; deleting a
            # user's file to satisfy a restore is not.
            await asyncio.to_thread(
                shutil.copytree, attachments_root, Path(settings.attachments_dir), dirs_exist_ok=True
            )
    _stage(on_stage, RunStage.DONE)


async def _roll_back(safety: BackupResult) -> None:
    stored = store.load(safety.name)
    assert stored.manifest is not None
    key = key_for(stored.manifest)
    with tempfile.TemporaryDirectory(prefix="radd-rollback-") as workspace:
        dump_path = Path(workspace) / art.DUMP_MEMBER
        await asyncio.to_thread(_extract_dump, stored, key, dump_path)
        await postgres.drop_public_schema()
        await postgres.restore_from(dump_path)
    await postgres.dispose_pool()


def _unpack(stored: StoredBackup, key: BackupKey | None, dump_path: Path, attachments_root: Path) -> None:
    """Blocking: open the artifact once, writing the dump and any attachments."""
    assert stored.manifest is not None
    found_dump = False
    with art.read_artifact(stored.path, stored.manifest, key=key) as tar:
        for member in tar:
            if member.name == art.DUMP_MEMBER:
                extracted = tar.extractfile(member)
                if extracted is not None:
                    with dump_path.open("wb") as handle:
                        shutil.copyfileobj(extracted, handle)
                    found_dump = True
            elif member.name.startswith(f"{art.ATTACHMENTS_MEMBER}/"):
                # `filter="data"` refuses absolute paths, `..`, links and device
                # nodes — an uploaded artifact is untrusted input.
                tar.extract(member, path=attachments_root.parent, filter="data")
    if not found_dump:
        raise BackupError(f"artifact contains no {art.DUMP_MEMBER}")


def upgrade_to_head() -> None:
    """`alembic upgrade head` in-process — the dump's schema may predate this build."""
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[3]  # src/radd/backup -> server/
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
