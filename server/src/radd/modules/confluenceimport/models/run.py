import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base

from ..types import RunKind, RunStage


class ConfluenceRun(Base):
    """One dry run, import or rollback. As with snapshots, the row is the progress
    bar — `stage`, `counts` and `problems` are rewritten in place and polled.

    `plan_snapshot` freezes the plan as it was when the run started, so a report
    read months later describes the decisions the run actually made rather than
    whatever the plan has been edited to since.
    """

    __tablename__ = "confluence_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("confluence_plans.id", ondelete="SET NULL"), nullable=True
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("confluence_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), default=RunKind.IMPORT.value)
    dry_run: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    plan_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    external_source: Mapped[str] = mapped_column(String(200), default="")

    stage: Mapped[str] = mapped_column(String(30), default=RunStage.PENDING.value)
    counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    problems: Mapped[list] = mapped_column(JSONB, default=list)
    #: Dry-run only: the per-page preview rows, bounded.
    report: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
