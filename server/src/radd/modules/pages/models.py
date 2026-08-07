import uuid
from datetime import datetime

from sqlalchemy import (
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
)
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class PageSpace(Base, TimestampMixin):
    """A wiki space: a named global page tree (spec 43).

    Slugs are cosmetic (globally unique for tidy display; URLs use ids).
    """

    __tablename__ = "page_spaces"
    __table_args__ = (UniqueConstraint("slug", name="uq_page_spaces_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    # Spec 74: opt-in PUBLIC space — readable without login via /public/pages.
    public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Page(Base, TimestampMixin):
    """A markdown page in a space's tree. `version` is the optimistic-concurrency
    guard (PATCH with a stale expected_version → 409); content-changing updates
    snapshot the PREVIOUS content into page_versions before bumping it.
    """

    __tablename__ = "pages"
    # The tree loads per space and expands per parent; the FTS expression GIN
    # index (to_tsvector('english', title || ' ' || body)) lives in the
    # migration — SQLAlchemy models can't express it declaratively.
    # `slug` is unique PER SPACE, not globally: two spaces may each have a
    # `getting-started`, and forcing global uniqueness would make the second one
    # `getting-started-2` for no reason a reader could see (RADD-702).
    __table_args__ = (
        Index("ix_pages_space_parent", "space_id", "parent_id"),
        UniqueConstraint("space_id", "slug", name="uq_pages_space_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("page_spaces.id", ondelete="CASCADE")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500))
    # The URL segment (RADD-702). Derived from the title at CREATE and then
    # FROZEN: renaming a page must not break links that already exist, so the
    # only thing that rewrites a slug is an explicit request to.
    slug: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
