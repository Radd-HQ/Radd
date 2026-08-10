import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base

from ..types import SnapshotStage


class ConfluenceSnapshot(Base):
    """One download of one selection — the cache everything else reads (spec 117).

    Cache-first is the spec-100 lesson: a selection is fetched ONCE and every later
    step (profiling, the macro census, planning, a dry run, the real run, a re-run
    after fixing a mapping) reads these rows. Nothing after the download touches
    the network, which is what makes iterating on mappings free.

    This row IS the progress bar. `stage`, `counts` and `problems` are rewritten as
    the download proceeds and polled by the UI — there is no separate job table and
    no event stream, because a download is one in-process asyncio task with exactly
    one observer.
    """

    __tablename__ = "confluence_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # SET NULL: a snapshot outlives the connection that produced it. Deleting a
    # connection must not silently destroy a cache someone is mid-import on.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("confluence_connections.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    #: The `Scope` value object, serialized. One column for all three selections.
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Recorded so a later run can say WHICH instance a page came from without
    #: re-reading the connection, which may have been edited or deleted since.
    external_source: Mapped[str] = mapped_column(String(200), default="")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    include_history: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    history_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    include_attachments: Mapped[bool] = mapped_column(Boolean, default=True)
    include_comments: Mapped[bool] = mapped_column(Boolean, default=True)

    stage: Mapped[str] = mapped_column(String(30), default=SnapshotStage.PENDING.value)
    counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    problems: Mapped[list] = mapped_column(JSONB, default=list)
    #: Instance vocabularies captured at download time (spaces, labels, users), so
    #: the plan can offer real choices without going back to the network.
    catalogs: Mapped[dict] = mapped_column(JSONB, default=dict)

    page_count: Mapped[int] = mapped_column(Integer, default=0)
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ConfluenceSnapshotPage(Base):
    """One cached page: its metadata, and its storage-format body verbatim.

    The body is stored RAW, not converted. Conversion is a function of the plan's
    mappings, and those change — re-running the converter over the same cache after
    fixing a macro mapping is the whole workflow, and it must not require a second
    download.
    """

    __tablename__ = "confluence_snapshot_pages"
    __table_args__ = (
        Index("ix_confluence_snapshot_pages_snapshot", "snapshot_id", "page_id"),
        Index("ix_confluence_snapshot_pages_parent", "snapshot_id", "parent_id"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("confluence_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    page_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_key: Mapped[str] = mapped_column(String(100), default="")
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[str] = mapped_column(Text, default="")
    #: The raw payload, for anything the columns above do not capture.
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Historical revisions, when the snapshot asked for them: a list of
    #: `{version, title, body, author, author_email, when}`. Inline rather than a
    #: table because they are read only as a whole page's history, never queried
    #: across pages.
    versions: Mapped[list] = mapped_column(JSONB, default=list)
    restrictions: Mapped[dict] = mapped_column(JSONB, default=dict)
    labels: Mapped[list] = mapped_column(JSONB, default=list)


class ConfluenceSnapshotComment(Base):
    """A cached comment. Footer and inline both live here; `anchor` is set for the
    inline ones and carries the text-quote selector `comments` already stores."""

    __tablename__ = "confluence_snapshot_comments"
    __table_args__ = (
        Index("ix_confluence_snapshot_comments_page", "snapshot_id", "page_id"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("confluence_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    comment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(64), default="")
    parent_comment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    author_email: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[str] = mapped_column(String(64), default="")
    anchor: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ConfluenceSnapshotAttachment(Base):
    """A cached attachment. The BYTES live on DISK inside the snapshot's package
    (see `snapshot/package.py`); this row is the manifest entry pointing at them.

    Not the object store: a download caches bytes that may never be imported, and
    pushing 49 GB of them through S3 to find that out made the download crawl.
    They reach the object store when a RUN imports them.
    """

    __tablename__ = "confluence_snapshot_attachments"
    __table_args__ = (
        Index("ix_confluence_snapshot_attachments_page", "snapshot_id", "page_id"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("confluence_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    attachment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(64), default="")
    filename: Mapped[str] = mapped_column(String(500), default="")
    content_type: Mapped[str] = mapped_column(String(200), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    #: RELATIVE to the package directory, so moving the package — or the whole
    #: snapshot root — does not invalidate every row in it.
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    download_path: Mapped[str] = mapped_column(String(1000), default="")
