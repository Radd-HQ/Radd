"""What a run created, so it can be undone (spec 117).

The `jiraimport.ledger` contract: record every write, in order, with a `before`
image narrowed to only the columns the import touched — so a restore cannot
clobber a column it never wrote. Rollback replays this backwards.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ConfluenceImportRecord


class LedgerEntity(StrEnum):
    SPACE = "page_space"
    PAGE = "page"
    COMMENT = "comment"
    ATTACHMENT = "attachment"
    GRANT = "access_grant"
    VERSION = "page_version"
    LABEL = "page_label"


class LedgerAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"


#: Undo order: children and content before the containers that hold them, so a
#: delete never trips a foreign key. Within an entity the order is the exact
#: reverse of write order, which is why the record id is a monotonic integer.
UNDO_ORDER: tuple[LedgerEntity, ...] = (
    LedgerEntity.GRANT,
    LedgerEntity.LABEL,
    LedgerEntity.VERSION,
    LedgerEntity.ATTACHMENT,
    LedgerEntity.COMMENT,
    LedgerEntity.PAGE,
    LedgerEntity.SPACE,
)

#: Rolling back the CONTENT while keeping the containers is the useful default: it
#: lets you fix a mapping and re-import without rebuilding the space.
CONTAINER_ENTITIES = frozenset({LedgerEntity.SPACE})


async def created(
    session: AsyncSession,
    run_id: uuid.UUID | None,
    entity: LedgerEntity,
    entity_id: uuid.UUID | str,
    *,
    subject: str = "",
) -> None:
    if run_id is None:  # a dry run writes nothing, so it records nothing
        return
    session.add(ConfluenceImportRecord(
        run_id=run_id,
        entity_type=entity.value,
        entity_id=str(entity_id),
        action=LedgerAction.CREATED.value,
        subject=subject[:300],
    ))


async def updated(
    session: AsyncSession,
    run_id: uuid.UUID | None,
    entity: LedgerEntity,
    entity_id: uuid.UUID | str,
    before: dict,
    *,
    subject: str = "",
) -> None:
    if run_id is None:
        return
    session.add(ConfluenceImportRecord(
        run_id=run_id,
        entity_type=entity.value,
        entity_id=str(entity_id),
        action=LedgerAction.UPDATED.value,
        subject=subject[:300],
        before=before,
    ))


def snapshot_of(row: object, columns: tuple[str, ...]) -> dict:
    """A deliberately NARROW before-image: only what the import writes."""
    out: dict = {}
    for column in columns:
        value = getattr(row, column, None)
        out[column] = str(value) if isinstance(value, uuid.UUID) else value
    return out


async def records_for(
    session: AsyncSession, run_id: uuid.UUID
) -> list[ConfluenceImportRecord]:
    result = await session.execute(
        select(ConfluenceImportRecord)
        .where(ConfluenceImportRecord.run_id == run_id)
        .order_by(ConfluenceImportRecord.id)
    )
    return list(result.scalars())
