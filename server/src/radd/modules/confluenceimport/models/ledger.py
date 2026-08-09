import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Identity,
    Index,
    String,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


class ConfluenceImportRecord(Base):
    """What one run created or changed, so it can be undone (spec 117).

    `id` is a `BigInteger Identity()` rather than a UUID deliberately: undo must be
    the exact inverse of write order, and a monotonic integer is the only key that
    orders itself. `before` holds only the columns the import actually touched, so
    restoring cannot clobber a column it never wrote.
    """

    __tablename__ = "confluence_import_records"
    __table_args__ = (Index("ix_confluence_import_records_run", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("confluence_runs.id", ondelete="CASCADE")
    )
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(20))  # created | updated
    subject: Mapped[str] = mapped_column(String(300), default="")
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ConfluencePendingRef(Base):
    """A link whose target had not been imported when its source body was written.

    Two cases produce these, and both are ordinary: a `PAGES` scope that links
    outside its own selection, and a space imported before the space it links to.
    Resolution is a later pass — or a later RUN entirely, which is exactly what the
    external identity on `pages` makes possible.
    """

    __tablename__ = "confluence_pending_refs"
    __table_args__ = (Index("ix_confluence_pending_refs_target", "target_page_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("confluence_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE")
    )
    external_source: Mapped[str] = mapped_column(String(200), default="")
    #: The FOREIGN id of the target, not a Radd one — that is the whole point.
    target_page_id: Mapped[str] = mapped_column(String(64))
    target_title: Mapped[str] = mapped_column(String(500), default="")
    resolved: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
