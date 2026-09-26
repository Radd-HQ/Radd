import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

# Spec 117: where a row came from when an importer made it — the key a
# re-import upserts on and cross-run links resolve through. `external_source`
# names the INSTANCE (`confluence:<host>`), not the product. Empty on native rows.
EXTERNAL_SOURCE_CHARS = 200
EXTERNAL_ID_CHARS = 200


def _external_unique(table: str) -> Index:
    """Unique `(source, id)` for rows that HAVE one — partial, because every
    native row carries the same empty pair."""
    return Index(
        f"uq_{table}_external",
        "external_source",
        "external_id",
        unique=True,
        postgresql_where=text("external_id <> ''"),
    )


class PageSpace(Base, TimestampMixin):
    """A wiki space: a named page tree; its unique slug is the first segment of
    every page path."""

    __tablename__ = "page_spaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_page_spaces_slug"),
        _external_unique("page_spaces"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    # Spec 117 — see EXTERNAL_SOURCE_CHARS above. A re-imported space must land in
    # the space it made, not create "Space PIP (2)".
    external_source: Mapped[str] = mapped_column(
        String(EXTERNAL_SOURCE_CHARS), default="", server_default=""
    )
    external_id: Mapped[str] = mapped_column(
        String(EXTERNAL_ID_CHARS), default="", server_default=""
    )


#: One sequence for every page on the instance — `pages.number` (migration
#: `d1233pagepath`).
PAGE_NUMBER_SEQUENCE = "pages_number_seq"


class Page(Base, TimestampMixin):
    """A markdown page in a space's tree. `version` is the optimistic-concurrency
    guard (PATCH with a stale expected_version → 409); content-changing updates
    snapshot the PREVIOUS content into page_versions before bumping it.
    """

    __tablename__ = "pages"
    # The FTS GIN index and the partial live-sibling slug index
    # `uq_pages_live_sibling_slug` live in the migration (not declarative).
    __table_args__ = (
        Index("ix_pages_space_parent", "space_id", "parent_id"),
        _external_unique("pages"),
    )
    # `number` is a SERVER default (the sequence): fetch it with the INSERT — a
    # lazy load after the flush is MissingGreenlet in an async session, which a
    # SQLAlchemy `Sequence()` default would produce.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # RADD-1233: the page's human key — what a permalink carries (`/pages?pageId=12402`).
    number: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        server_default=text(f"nextval('{PAGE_NUMBER_SEQUENCE}')"),
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("page_spaces.id", ondelete="CASCADE")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500))
    # The page's path segment (RADD-702, RADD-1233): derived at create, then
    # FROZEN except on request or a move/restore dodging a live sibling; every
    # rewrite leaves the old path in `page_path_history`.
    slug: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Spec 117 — see EXTERNAL_SOURCE_CHARS above.
    external_source: Mapped[str] = mapped_column(
        String(EXTERNAL_SOURCE_CHARS), default="", server_default=""
    )
    external_id: Mapped[str] = mapped_column(
        String(EXTERNAL_ID_CHARS), default="", server_default=""
    )


class PageVersion(Base):
    """Immutable snapshot of a page's PREVIOUS content: version N's row is
    written when version N+1 becomes current (so the live row is never
    duplicated into the history)."""

    __tablename__ = "page_versions"
    __table_args__ = (UniqueConstraint("page_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PagePathHistory(Base):
    """An address this page USED to answer to (RADD-1233), written for the page
    and every descendant whose path changed. The resolver's EXACT second step, so
    an old link lands on the page it named, never on a same-named neighbour."""

    __tablename__ = "page_path_history"
    __table_args__ = (Index("ix_page_path_history_space_path", "space_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), index=True
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("page_spaces.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PageLink(Base):
    """Page → page reference (RADD-713): a derived index rebuilt from the body on
    save; both sides cascade."""

    __tablename__ = "page_links"

    source_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    target_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PageLabel(Base):
    """Page <-> label (RADD-718): the association is pages', the label rows the
    `labels` module's — one vocabulary for issues and pages."""

    __tablename__ = "page_labels"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PageTemplate(Base, TimestampMixin):
    """A shape a recurring page starts from (RADD-712); `space_id` NULL = every space."""

    __tablename__ = "page_templates"
    __table_args__ = (UniqueConstraint("name", name="uq_page_templates_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(40), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    space_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_spaces.id", ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PageWatcher(Base):
    """Someone following a page (RADD-719) — local because `notify.ItemWatcher`
    is keyed to work_items by FK; the notification side is shared."""

    __tablename__ = "page_watchers"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    #: Plain UUID, no FK — the same convention notify uses for watchers.
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ItemPageLink(Base):
    """Issue ↔ page link. `derived` rows are owned by the page text and
    reconciled on every save (RADD-943); manual rows are user data. A key both
    mentioned and linked stays manual."""

    __tablename__ = "item_page_links"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    derived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
