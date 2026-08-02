import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ItemVcsLink(Base, TimestampMixin):
    """A version-control reference (branch, commit, MR/PR) linked to a work item — the
    "Version control / Development" panel. Added manually now; populated by connectors
    (GitLab/GitHub/Forgejo) later via the upsert write-seam in service.py."""

    __tablename__ = "item_vcs_links"

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
    # Who linked it; None for connector/system. Plain UUID (no FK) — mirrors events.actor_id.
    created_by: Mapped[uuid.UUID | None]
