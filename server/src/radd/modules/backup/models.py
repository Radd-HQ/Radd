"""Backup schedules and run history (spec 99).

The ARTIFACTS are not in the database: a restore rewrites it, so a table of backups would
roll its inventory back and erase the safety backup taken seconds earlier. The directory is
the inventory (`radd.backup.store`). Schedules and runs are configuration and history, which
a restore rightly reverts.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class BackupSchedule(Base, TimestampMixin):
    """When to take a backup, and how many to keep. `config` is the shared `radd.schedule`
    shape; `next_run_at` is the claim point — due rows are selected `FOR UPDATE SKIP LOCKED`,
    so two workers never take the same backup."""

    __tablename__ = "backup_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    include_attachments: Mapped[bool] = mapped_column(Boolean, default=True)
    keep_last: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keep_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BackupRun(Base, TimestampMixin):
    """One backup or restore — the row IS the progress bar: `stage` and `status` are committed
    as work proceeds. A restart abandons the task, so runs left RUNNING at startup are marked
    interrupted."""

    __tablename__ = "backup_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))  # RunKind
    status: Mapped[str] = mapped_column(String(20))  # RunStatus
    stage: Mapped[str] = mapped_column(String(30))  # RunStage
    artifact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # BigInteger: an artifact can exceed 2 GB.
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("backup_schedules.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
