"""Recording what an import did, so it can be undone (spec 100).

Every write goes through here. Rollback replays the ledger in reverse `id` order,
which is why the id is a monotonic sequence rather than a timestamp: undo order
has to be the exact inverse of write order, and two writes land in the same
millisecond constantly.

A CREATED row records only the identity — rollback deletes it. An UPDATED row
records a `before` image of JUST the columns the import touched, so restoring it
cannot clobber a change someone made to a different column of the same record.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import JiraImportRecord
from .types import LedgerAction, LedgerEntity

# Reverse dependency order for rollback: content before the schema it depends on,
# children before parents. Deleting a state while items still point at it, or a
# project before its items, would simply fail.
UNDO_ORDER: tuple[LedgerEntity, ...] = (
    LedgerEntity.WEB_LINK,
    LedgerEntity.ITEM_LINK,
    LedgerEntity.ATTACHMENT,
    LedgerEntity.WORKLOG,
    LedgerEntity.COMMENT,
    LedgerEntity.ITEM,
    LedgerEntity.CYCLE,
    LedgerEntity.RELEASE,
    LedgerEntity.TEAM,
    LedgerEntity.ISSUE_TYPE,
    LedgerEntity.STATE,
    LedgerEntity.FIELD,
    LedgerEntity.LINK_TYPE,
    LedgerEntity.USER,
    LedgerEntity.PROJECT,
)

# Entities that are the TARGET SCHEMA rather than imported content — so "undo the
# issues but keep the project and its fields" is expressible.
SCHEMA_ENTITIES: frozenset[LedgerEntity] = frozenset(
    {
        LedgerEntity.PROJECT,
        LedgerEntity.FIELD,
        LedgerEntity.STATE,
        LedgerEntity.ISSUE_TYPE,
        LedgerEntity.LINK_TYPE,
        LedgerEntity.USER,
    }
)


def created(
    session: AsyncSession,
    run_id: uuid.UUID,
    entity: LedgerEntity,
    entity_id: object,
    *,
    subject: str = "",
) -> None:
    session.add(
        JiraImportRecord(
            run_id=run_id,
            entity_type=entity.value,
            entity_id=str(entity_id),
            action=LedgerAction.CREATED.value,
            subject=subject[:200],
            before={},
            is_schema=entity in SCHEMA_ENTITIES,
        )
    )


def updated(
    session: AsyncSession,
    run_id: uuid.UUID,
    entity: LedgerEntity,
    entity_id: object,
    before: dict[str, Any],
    *,
    subject: str = "",
) -> None:
    """`before` must contain ONLY the columns this import is about to change."""
    session.add(
        JiraImportRecord(
            run_id=run_id,
            entity_type=entity.value,
            entity_id=str(entity_id),
            action=LedgerAction.UPDATED.value,
            subject=subject[:200],
            before=before,
            is_schema=entity in SCHEMA_ENTITIES,
        )
    )


def snapshot_of(row: object, columns: tuple[str, ...]) -> dict[str, Any]:
    """A JSON-safe before-image of the named columns."""
    out: dict[str, Any] = {}
    for column in columns:
        value = getattr(row, column, None)
        if isinstance(value, uuid.UUID):
            out[column] = str(value)
        elif hasattr(value, "isoformat"):
            out[column] = value.isoformat()
        else:
            out[column] = value
    return out


async def records_for(
    session: AsyncSession, run_id: uuid.UUID, *, schema: bool | None = None
) -> list[JiraImportRecord]:
    """The run's ledger, newest first — the order rollback undoes in."""
    query = select(JiraImportRecord).where(JiraImportRecord.run_id == run_id)
    if schema is not None:
        query = query.where(JiraImportRecord.is_schema.is_(schema))
    result = await session.execute(query.order_by(JiraImportRecord.id.desc()))
    return list(result.scalars())
