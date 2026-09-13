import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, text
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
