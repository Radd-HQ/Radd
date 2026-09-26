import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from ..types import SnapshotStage


class JiraSnapshot(Base, TimestampMixin):
    """A cached download of one JQL result set. Everything downstream reads these rows,
    never Jira; the row is the progress bar; `catalogs` holds the instance
    vocabularies (incl. the field catalog's stable `schema.custom` keys)."""

    __tablename__ = "jira_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Kept for provenance; a snapshot outlives the connection that produced it,
    # because re-importing from cache needs no connection at all.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jira_connections.id", ondelete="SET NULL")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    jira_project_key: Mapped[str] = mapped_column(String(100))
    jql: Mapped[str] = mapped_column(Text)
    # What the admin asked for — attachments and history multiply the download.
    include_attachments: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    include_history: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)

    stage: Mapped[str] = mapped_column(String(20), default=SnapshotStage.PENDING.value)
    counts: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    problems: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    catalogs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    issue_count: Mapped[int] = mapped_column(Integer, default=0)
    # Sized so the UI can show what a snapshot costs and offer to delete it.
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()


class JiraSnapshotIssue(Base):
    """One cached Jira issue, exactly as Jira returned it.

    Raw JSON on purpose: the transform is pure and re-runnable, so a mapping fix
    or a bug fix re-reads the ORIGINAL payload rather than something already
    lossily interpreted. Comment/worklog/changelog backfills are merged INTO this
    payload, so an issue is complete in one row.
    """

    __tablename__ = "jira_snapshot_issues"
    __table_args__ = (
        # The read pattern is "walk one snapshot in key order" (the import) and
        # "look up one key" (relinking, dry-run detail).
        Index("ix_jira_snapshot_issues_snapshot", "snapshot_id", "jira_key"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jira_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    jira_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    jira_id: Mapped[str] = mapped_column(String(30), default="")
    # Jira's own `fields.updated`, so a later re-download can tell what changed.
    jira_updated_at: Mapped[datetime | None] = mapped_column()
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class JiraSnapshotBlob(Base):
    """One downloaded attachment binary belonging to a snapshot (spec 100).

    The bytes go to the ordinary attachment store (filesystem or S3) — binaries do
    not belong in JSONB — and this row is the index that maps a Jira attachment id
    to its `storage_name`. Deleting a snapshot enumerates these to remove the
    blobs, so "delete" really reclaims the space.
    """

    __tablename__ = "jira_snapshot_blobs"
    __table_args__ = (Index("ix_jira_snapshot_blobs_snapshot", "snapshot_id"),)

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jira_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    jira_attachment_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    jira_key: Mapped[str] = mapped_column(String(100), default="")
    storage_name: Mapped[str] = mapped_column(String(64))
    # Which storage host holds the bytes (NULL = the default host).
    storage_host_id: Mapped[uuid.UUID | None] = mapped_column()
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
