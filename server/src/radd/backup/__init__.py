"""Backups (spec 99) — core, because the CLI must restore an EMPTY database.

Nothing here imports FastAPI, the plugin registry, or an ORM model: a disaster
recovery starts with a fresh deployment where none of those can load.
`radd.modules.backup` wraps these functions for the API and owns the schedules.
"""

from .artifact import ArtifactInvalid, Manifest, is_valid_name, new_artifact_name, read_manifest
from .crypto import ArtifactCorrupt, BackupKey, BackupKeyError, load_key
from .errors import BackupError
from .service import (
    BackupResult,
    Compatibility,
    active_key,
    compatibility,
    create_backup,
    restore_backup,
    verify,
)
from .store import DirectoryStatus, StoredBackup, directory_status, listing, load, prunable
from .types import BackupEntity, BackupEvent, BackupKind, RunKind, RunStage, RunStatus

__all__ = [
    "ArtifactCorrupt",
    "ArtifactInvalid",
    "BackupEntity",
    "BackupError",
    "BackupEvent",
    "BackupKey",
    "BackupKeyError",
    "BackupKind",
    "BackupResult",
    "Compatibility",
    "DirectoryStatus",
    "Manifest",
    "RunKind",
    "RunStage",
    "RunStatus",
    "StoredBackup",
    "active_key",
    "compatibility",
    "create_backup",
    "directory_status",
    "is_valid_name",
    "listing",
    "load",
    "load_key",
    "new_artifact_name",
    "prunable",
    "read_manifest",
    "restore_backup",
    "verify",
]
