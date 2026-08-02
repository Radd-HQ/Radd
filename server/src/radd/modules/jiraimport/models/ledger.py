import uuid
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, Index, String, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class JiraImportRecord(Base, TimestampMixin):
    """The provenance ledger (spec 100) — what an import did, so it can be undone.

    Spec 90 had no equivalent: a bad import was unwound by hand-written SQL (which
    is literally what its own tests did). Every write records here, and rollback
    replays it in reverse.

    `before` is the crux. For a CREATED entity it is empty and rollback deletes
    the row; for an UPDATED one it holds a snapshot of JUST the fields the import
    touched, so rollback restores them without clobbering anything a human changed
    elsewhere on the same record.

    A monotonic `id` rather than a timestamp: rollback order has to be the exact
    reverse of write order, and two writes in the same millisecond are common.
    """

    __tablename__ = "jira_import_records"
    __table_args__ = (Index("ix_jira_import_records_run", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jira_runs.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40))  # LedgerEntity
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(10))  # created | updated
    # "" for issues; the Jira key/value this row came from, for the rollback report.
    subject: Mapped[str] = mapped_column(String(200), default="")
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Schema (project/fields/states/types) vs content (items/comments/worklogs), so
    # a rollback can undo the issues and keep the provisioned schema.
    is_schema: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)


class JiraPendingRef(Base, TimestampMixin):
    """A cross-project reference that could not be resolved yet (spec 100).

    The answer to "I import DEV first, but it links to TD which I haven't imported".
    Spec 90 dropped a dead web link and never looked again; relinking is now a
    repeatable pass over these rows, run after every import and on demand, which
    turns the placeholder into a real link the moment its target arrives.
    """

    __tablename__ = "jira_pending_refs"
    __table_args__ = (
        # The relink pass scans by target key: "what is still waiting for TD-*".
        Index("ix_jira_pending_refs_target", "target_jira_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jira_runs.id", ondelete="SET NULL")
    )
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))  # PendingRefKind: parent | link
    target_jira_key: Mapped[str] = mapped_column(String(100))
    link_type: Mapped[str] = mapped_column(String(30), default="")
    inward: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    # The stand-in web link, removed when the real reference finally resolves.
    web_link_id: Mapped[uuid.UUID | None] = mapped_column()
