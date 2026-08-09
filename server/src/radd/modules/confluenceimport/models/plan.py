import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ConfluencePlan(Base, TimestampMixin):
    """The editable decisions between a snapshot and an import (spec 117).

    All six mapping tables live in ONE JSONB document, read and written whole. Not
    six tables: they are edited together in one form, saved together, and never
    queried across plans — the join table would be ceremony with no reader.
    """

    __tablename__ = "confluence_plans"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("confluence_snapshots.id", ondelete="CASCADE")
    )
    #: `PlanMappings` — spaces, macros, users, groups, labels, jira_links.
    mappings: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: `PlanOptions` — quiet, history, the unresolved-principal fallback.
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    provisioned_at: Mapped[datetime | None] = mapped_column(nullable=True)
