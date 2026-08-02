"""The backup directory (spec 99 §3) — the inventory, and what may be pruned.

**The directory is the inventory, not a database table.** A restore rewrites the
database, so a `backups` table would roll its own listing back to whatever the
restored snapshot knew — erasing, among other things, the record of the safety
backup taken seconds earlier. Listing therefore reads each file's plaintext
header, which needs no key.

Retention only ever prunes SCHEDULED artifacts, and only those from the schedule
being pruned. Manual, uploaded and pre-restore artifacts were created by a
deliberate act; deleting someone's explicit backup to satisfy a rotation policy
is not a rotation policy. The newest healthy artifact is never removed, whatever
the numbers say.
"""

import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from radd.config import settings

from . import artifact as art
from .artifact import ArtifactInvalid, Manifest
from .types import BackupKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredBackup:
    """One artifact on disk, as the API and the pruner see it."""

    name: str
    path: Path
    size_bytes: int
    manifest: Manifest | None  # None = unreadable header (foreign or corrupt file)
    complete: bool  # a footer is present, so the write finished
    problem: str | None = None

    @property
    def created_at(self) -> datetime:
        if self.manifest is not None:
            try:
                return datetime.fromisoformat(self.manifest.created_at)
            except ValueError:
                pass
        return datetime.fromtimestamp(self.path.stat().st_mtime, UTC)

    @property
    def kind(self) -> str:
        return self.manifest.kind if self.manifest else BackupKind.UPLOADED.value


def backup_dir() -> Path:
    return Path(settings.backup_dir)


def ensure_dir() -> Path:
    """Create the directory 0700 if missing. Never raises — an unwritable
    directory is reported by `directory_status`, not thrown at startup."""
    path = backup_dir()
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        logger.warning("backup directory %s is not usable: %s", path, exc)
    return path


@dataclass(frozen=True)
class DirectoryStatus:
    path: str
    exists: bool
    writable: bool
    free_bytes: int | None
    problem: str | None


def directory_status() -> DirectoryStatus:
    """Whether backups can be written here, in words an operator can act on.

    The common failure is a bind-mounted host directory owned by the host user:
    the container runs as uid 10001 and simply cannot write to it."""
    path = ensure_dir()
    import os

    if not path.exists():
        return DirectoryStatus(str(path), False, False, None, f"{path} does not exist and could not be created")
    if not os.access(path, os.W_OK | os.X_OK):
        return DirectoryStatus(
            str(path),
            True,
            False,
            None,
            f"{path} is not writable by this process (uid {os.getuid()}); "
            f"for a bind mount, chown it to the container user",
        )
    return DirectoryStatus(str(path), True, True, shutil.disk_usage(path).free, None)


def load(name: str) -> StoredBackup:
    """One artifact by name. Raises `ArtifactInvalid` for a name that is a path."""
    path = art.resolve_in(backup_dir(), name)
    if not path.is_file():
        raise FileNotFoundError(name)
    return _describe(path)


def _describe(path: Path) -> StoredBackup:
    size = path.stat().st_size
    try:
        manifest = art.read_manifest(path)
    except (ArtifactInvalid, OSError) as exc:
        return StoredBackup(path.name, path, size, None, False, str(exc))
    complete = art.read_footer(path) is not None
    return StoredBackup(
        path.name,
        path,
        size,
        manifest,
        complete,
        None if complete else "incomplete — the backup did not finish",
    )


def listing() -> list[StoredBackup]:
    """Every artifact, newest first. Foreign files are ignored, not errors."""
    path = ensure_dir()
    if not path.is_dir():
        return []
    found = [
        _describe(child)
        for child in path.iterdir()
        if child.is_file() and art.is_valid_name(child.name)
    ]
    return sorted(found, key=lambda item: item.created_at, reverse=True)


def delete(name: str) -> None:
    art.resolve_in(backup_dir(), name).unlink()


def prunable(
    backups: list[StoredBackup],
    *,
    schedule_id: str,
    keep_last: int | None,
    keep_days: int | None,
    now: datetime | None = None,
) -> list[StoredBackup]:
    """Which artifacts this schedule's retention policy would remove.

    Pure, so the policy is unit-testable without touching a disk. Candidates are
    only this schedule's own SCHEDULED artifacts; incomplete ones are pruned
    first regardless of count, since they are not backups at all.
    """
    moment = now or datetime.now(UTC)
    mine = [
        backup
        for backup in backups
        if backup.manifest is not None
        and backup.manifest.kind == BackupKind.SCHEDULED.value
        and backup.manifest.schedule_id == schedule_id
    ]
    mine.sort(key=lambda item: item.created_at, reverse=True)

    healthy = [item for item in mine if item.complete]
    doomed = {item.name: item for item in mine if not item.complete}

    if keep_last is not None and keep_last > 0:
        for item in healthy[keep_last:]:
            doomed[item.name] = item
    if keep_days is not None and keep_days > 0:
        cutoff = moment - timedelta(days=keep_days)
        for item in healthy:
            if item.created_at < cutoff:
                doomed[item.name] = item

    # Never leave the schedule with nothing: keep the newest healthy artifact
    # even if the policy says otherwise.
    if healthy:
        doomed.pop(healthy[0].name, None)
    return [item for item in mine if item.name in doomed]


def free_bytes() -> int:
    return shutil.disk_usage(ensure_dir()).free


def estimated_size(backups: list[StoredBackup], fallback: int) -> int:
    """1.5x the last successful artifact, else the caller's fallback (the
    database size). Deliberately generous — refusing a backup for want of space
    is recoverable; filling the volume the database lives on is not."""
    healthy = [item.size_bytes for item in backups if item.complete]
    return int(healthy[0] * 1.5) if healthy else fallback
