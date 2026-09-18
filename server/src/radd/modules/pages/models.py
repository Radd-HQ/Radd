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

# Spec 117. Where a row came from, when something outside Radd made it.
#
# The Jira importer never needed this: it maps `DEV-123` onto Radd `DEV-123`, so
# the item KEY is the external identity and a re-import upserts on it. A page has
# no such handle — a UUID, and a slug that is cosmetic and frozen after create —
# so without a column the mapping lives only in an importer's run ledger, which is
# scoped to one run, deleted by its rollback, and gone when the plugin is removed.
# That breaks re-import (duplicates instead of updates), cross-run link resolution
# (import one space in March and another in June) and provenance.
#
# `external_source` names the INSTANCE, not the product — `confluence:<host>` —
# because two Confluence servers both have a page `12345`. Generic on purpose:
# `pages` must not learn the word Confluence, and the next importer must not have
# to invent its own map table. Empty on everything a person made here.
EXTERNAL_SOURCE_CHARS = 200
EXTERNAL_ID_CHARS = 200


def _external_unique(table: str) -> Index:
    """Unique `(source, id)` — but only for rows that HAVE one.

    Partial, because every natively-created row carries the same empty pair and a
    plain unique constraint would let exactly one of them exist.
    """
    return Index(
        f"uq_{table}_external",
        "external_source",
        "external_id",
        unique=True,
        postgresql_where=text("external_id <> ''"),
    )


class PageSpace(Base, TimestampMixin):
    """A wiki space: a named global page tree (spec 43).

    Slugs are cosmetic (globally unique for tidy display; URLs use ids).
    """

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


#: One sequence for every page on the instance — `pages.number`. Created by
#: the `d1233pagepath` migration; the column's SERVER default draws from it, so
#: the value comes back with the INSERT (eager_defaults) instead of as a
#: post-flush lazy load — which in an async session is the MissingGreenlet
#: error, and is exactly what a SQLAlchemy `Sequence()` default produces.
PAGE_NUMBER_SEQUENCE = "pages_number_seq"


class Page(Base, TimestampMixin):
    """A markdown page in a space's tree. `version` is the optimistic-concurrency
    guard (PATCH with a stale expected_version → 409); content-changing updates
    snapshot the PREVIOUS content into page_versions before bumping it.
    """

    __tablename__ = "pages"
    # The tree loads per space and expands per parent; the FTS expression GIN
    # index (to_tsvector('english', title || ' ' || body)) lives in the
    # migration — SQLAlchemy models can't express it declaratively.
    # RADD-1233: `slug` is unique among LIVE SIBLINGS only — the partial
    # expression index `uq_pages_live_sibling_slug` (space, coalesce(parent),
    # slug WHERE archived_at IS NULL) also lives in the migration. The id is the
    # page's key; the slug is the segment it contributes to a PATH, and a path
    # is unambiguous exactly when siblings differ. Two pages under different
    # parents may share a name; an archived page no longer squats on its.
    __table_args__ = (
        Index("ix_pages_space_parent", "space_id", "parent_id"),
        _external_unique("pages"),
    )
    # `number` comes from the database (the sequence); fetch it with the INSERT
    # rather than on first read — in an async session a lazy attribute load
    # after the flush is the MissingGreenlet error.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # RADD-1233: the page's HUMAN key — a small instance-wide integer from one
    # sequence, the way an issue has `RADD-1233`. It is what a permalink
    # carries (`/pages?pageId=12402`): a UUID in an address nobody can read,
    # type or say aloud is an identifier only a database could love.
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
    # The page's segment of its URL path (RADD-702, RADD-1233). Derived from the
    # title at CREATE and then FROZEN: the only things that rewrite a slug are
    # an explicit request, and a move or restore that lands beside a live
    # sibling already using it. Every rewrite leaves the old value in
    # `page_path_history` (the page's whole old path), so a stale link still
    # finds the page.
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
    """An address this page USED to answer to (RADD-1233).

    Written whenever a page's path changes — an explicit rename, a move, a
    restore that had to dodge a live sibling — for the page AND every
    descendant whose path changed with it. The resolver's second step: a path
    that no longer walks the tree is looked up here EXACTLY, so the address
    somebody copied last month lands on the page it named, never on a
    same-named neighbour. Rows go with the page.
    """

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
    """Page → page reference, maintained on save (RADD-713).

    A derived index, not user data: it is rebuilt from the body on every write,
    so it can be dropped and recreated by a reindex without losing anything.
    Both sides cascade — a deleted page should not leave a backlink pointing at
    nothing, nor appear as one.
    """

    __tablename__ = "page_links"

    source_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    target_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PageLabel(Base):
    """Page <-> label (RADD-718).

    The association lives HERE, in pages, while the label rows stay the `labels`
    module's — the same split items uses. A page label and an issue label are the
    same label on purpose: "runbook" meaning one thing on an issue and another on
    a page is how a tag vocabulary rots.
    """

    __tablename__ = "page_labels"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PageTemplate(Base, TimestampMixin):
    """A shape a recurring page starts from (RADD-712).

    `space_id` NULL = available everywhere; set = that space only. Scoping by
    absence rather than by a join table, because a template belongs to one place
    or to all — there is no third case, and the association table would be two
    rows of ceremony per template.
    """

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
    """Someone following a page (RADD-719).

    Pages own this rather than notify: `notify.ItemWatcher` is keyed to
    work_items by foreign key, and the alternative — making watchers polymorphic
    too — is a second migration of a hot table for one extra parent. The
    NOTIFICATION side is shared; only the subscription list is local.
    """

    __tablename__ = "page_watchers"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    #: Plain UUID, no FK — the same convention notify uses for watchers.
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ItemPageLink(Base):
    """Issue ↔ doc-page association (both directions surface it).

    `derived` splits the table in two (RADD-943). A MANUAL row is user data:
    someone typed a key, and no body edit may remove it. A DERIVED row is owned
    by the page's text — reconciled wholesale on every body change from the
    issue references the body actually carries, so deleting the mention deletes
    the link. The same split `item_links` expresses through `link_type`
    (`mentions` vs. the manual types), which items has maintained since spec 52.

    A key that is both mentioned and manually linked stays manual: the manual
    row records a decision, and the mention is only evidence.
    """

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
