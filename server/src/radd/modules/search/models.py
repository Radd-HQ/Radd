import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


class SearchIndexRow(Base):
    """One row per item: denormalized searchable text + the weighted tsvector.

    Maintained by the outbox indexer (never written by request handlers). The
    text columns exist so any one signal (a comment edit) can recompute `tsv`
    without re-reading the other modules' tables.
    """

    __tablename__ = "search_index"
    # Key-prefix quick-open scans the table (ILIKE) — fine at studio row counts;
    # only the tsv gets a real (GIN) index.
    __table_args__ = (Index("ix_search_index_tsv", "tsv", postgresql_using="gin"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(index=True)
    key: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    comments_text: Mapped[str] = mapped_column(Text, default="")
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
