import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from ..types import RunStage


class JiraRun(Base, TimestampMixin):
    """One execution over a snapshot (spec 100) — a dry run, an import, or a rollback.

    The same row shape for all three because they are the same pipeline: a dry run
    builds every operation and reports, an import builds the same operations and
    applies them, a rollback walks the ledger backwards. Sharing the row means the
    progress UI, the problem list and the history are written once.

    The row IS the progress bar (the house idiom): `stage`, `counts` and
    `problems` are rewritten and committed as work proceeds.
    """

    __tablename__ = "jira_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jira_plans.id", ondelete="SET NULL")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jira_snapshots.id", ondelete="SET NULL")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20))  # RunKind: dry_run | import | rollback
    dry_run: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    # A snapshot of the plan, so editing or deleting it never rewrites history and
    # the run stays reproducible.
    plan_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    stage: Mapped[str] = mapped_column(String(20), default=RunStage.PENDING.value)
    counts: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    problems: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    # Dry-run only: the per-issue plan, so the report can be read without re-running.
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
