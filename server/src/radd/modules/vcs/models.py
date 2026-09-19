import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ItemVcsLink(Base, TimestampMixin):
    """A version-control reference (branch, commit, MR/PR) linked to a work item — the
    "Version control / Development" panel. Added manually now; populated by connectors
    (GitLab/GitHub/Forgejo) later via the upsert write-seam in service.py."""

    __tablename__ = "item_vcs_links"
    __table_args__ = (
        # RADD-1124: one row per ref per item. Connector ids are canonical
        # (`ids.py`), so the index is what makes a re-delivered push, a backfill
        # after a webhook, or two deliveries racing land on ONE row. Manual
        # links carry no external id and are left out of it.
        Index(
            "uq_item_vcs_links_ref",
            "item_id",
            "provider",
            "external_id",
            unique=True,
            postgresql_where=text("external_id <> ''"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    ref_type: Mapped[str] = mapped_column(String(20))  # VcsRefType
    provider: Mapped[str] = mapped_column(String(20), default="manual")  # VcsProvider
    title: Mapped[str] = mapped_column(String(300))  # e.g. "feature/login" or "Fix login (!42)"
    url: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(40), default="")  # free-form: "open"/"merged"/"closed"
    external_id: Mapped[str] = mapped_column(String(200), default="")  # connector id for upsert dedup
    # Spec 111 — the LATEST CI run for this ref, not a check-run history. The
    # panel answers "is this green"; a branch with two workflows shows the last
    # one to report.
    ci_state: Mapped[str] = mapped_column(String(20), default="")  # CiState ("" = unknown)
    ci_url: Mapped[str] = mapped_column(String(2000), default="")
    ci_updated_at: Mapped[datetime | None] = mapped_column(default=None)
    # Who linked it; None for connector/system. Plain UUID (no FK) — mirrors events.actor_id.
    created_by: Mapped[uuid.UUID | None]


class VcsUserLink(Base, TimestampMixin):
    """A provider account → Radd user mapping (RADD-1258).

    Filled two ways: AUTOMATICALLY when a provider user's email matches a Radd
    account (`matched_by = email`), and BY HAND in Settings → Version control
    when the host hides emails (GitHub does) or the token cannot read them
    (`matched_by = manual`). Keyed per connection: the same username on two
    GitLab hosts may be two people.
    """

    __tablename__ = "vcs_user_links"
    __table_args__ = (
        UniqueConstraint(
            "provider", "connection_id", "external_username", name="uq_vcs_user_links_account"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20))  # VcsProvider
    # The connector's connection row. No FK: each connector owns its own table
    # (forgejo_connections, github_connections, gitlab_connections); the
    # connector deletes these rows when it deletes a connection.
    connection_id: Mapped[uuid.UUID] = mapped_column(index=True)
    external_username: Mapped[str] = mapped_column(String(200))  # stored lowercase
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    matched_by: Mapped[str] = mapped_column(String(20))  # VcsMatchedBy


class VcsPendingWorklog(Base, TimestampMixin):
    """A time entry whose author has no Radd account yet (RADD-1258).

    Held here instead of logged against the wrong person or a system account —
    a worklog on the wrong author makes the timesheet lie. The "unmatched
    authors" list in Settings is DERIVED from these rows (GROUP BY username);
    mapping the username replays them into real worklogs and deletes them.
    Keyed by the provider's own entry id, so a re-delivery updates in place,
    and scoped by the ref (`external_scope`) so a reconcile can drop the ones
    the source no longer has.
    """

    __tablename__ = "vcs_pending_worklogs"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_vcs_pending_worklogs_entry"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20))
    connection_id: Mapped[uuid.UUID] = mapped_column(index=True)
    external_scope: Mapped[str] = mapped_column(String(200), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    external_username: Mapped[str] = mapped_column(String(200), index=True)  # lowercase
    external_email: Mapped[str] = mapped_column(String(320), default="")
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), nullable=True
    )
    worked_on: Mapped[date] = mapped_column(Date)
    time_spent_seconds: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    last_seen_at: Mapped[datetime] = mapped_column()
