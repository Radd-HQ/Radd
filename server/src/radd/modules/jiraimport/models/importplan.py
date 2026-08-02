import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class JiraPlan(Base, TimestampMixin):
    """One import's complete set of decisions (spec 100).

    Bound to a SNAPSHOT, not to a live JQL: the plan is edited, provisioned,
    dry-run and committed against cached data, so every step is repeatable and
    none of them touch Jira.

    `mappings` holds all nine tables (fields + eight vocabularies) in one JSONB
    document — it is always read and written whole, so a column beats nine child
    tables. `radd_project_id` is filled in by provisioning: before that the plan
    names a project that does not exist yet, which is exactly the "create the
    schema locally before importing" step.
    """

    __tablename__ = "jira_plans"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jira_snapshots.id", ondelete="CASCADE")
    )
    # Set once the plan has been provisioned — the target really exists from then on.
    radd_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    radd_project_key: Mapped[str] = mapped_column(String(20))
    radd_project_name: Mapped[str] = mapped_column(String(200))
    mappings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    provisioned_at: Mapped[datetime | None] = mapped_column()
