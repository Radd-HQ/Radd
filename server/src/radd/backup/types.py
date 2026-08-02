"""Backup vocabulary (dev rule 2: no magic strings)."""

from enum import StrEnum


class BackupKind(StrEnum):
    """Why an artifact exists. Drives retention: only SCHEDULED artifacts are
    ever auto-pruned — the rest were created by a deliberate act."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    PRE_RESTORE = "pre_restore"
    UPLOADED = "uploaded"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunKind(StrEnum):
    BACKUP = "backup"
    RESTORE = "restore"


class RunStage(StrEnum):
    """The run row is the progress bar (the jiraimport idiom)."""

    QUEUED = "queued"
    DUMPING = "dumping"
    PACKING = "packing"
    VERIFYING = "verifying"
    PRUNING = "pruning"
    # restore-only
    SAFETY_BACKUP = "safety_backup"
    DRAINING = "draining"
    RESTORING = "restoring"
    MIGRATING = "migrating"
    ATTACHMENTS = "attachments"
    DONE = "done"


class BackupEntity(StrEnum):
    """Entity names for NotFoundError/ConflictError and event payloads."""

    BACKUP = "backup"
    SCHEDULE = "backup_schedule"
    RUN = "backup_run"


class BackupEvent(StrEnum):
    """Emitted to the events outbox, which is what puts them in the audit log."""

    CREATED = "backup.created"
    DELETED = "backup.deleted"
    UPLOADED = "backup.uploaded"
    RESTORED = "backup.restored"
    SCHEDULE_CREATED = "backup_schedule.created"
    SCHEDULE_UPDATED = "backup_schedule.updated"
    SCHEDULE_DELETED = "backup_schedule.deleted"
