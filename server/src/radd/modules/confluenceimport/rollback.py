"""Undoing a run (spec 117).

Replay the ledger backwards. Each row runs inside its own SAVEPOINT so one
stubborn foreign key does not abort the rest — the `jiraimport.rollback` contract,
and the reason a partial rollback is still useful.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .ledger import CONTAINER_ENTITIES, UNDO_ORDER, LedgerAction, LedgerEntity
from .models import ConfluenceImportRecord, ConfluencePendingRef, ConfluenceRun
from .schemas import RollbackPreflight

logger = logging.getLogger(__name__)

#: Deleted with a raw statement rather than through each module's service,
#: deliberately: rollback must not re-run permission checks (the actor may differ)
#: nor emit deletion events for content that, as far as the instance is concerned,
#: was never really there.
_TABLES = {
    LedgerEntity.SPACE: "page_spaces",
    LedgerEntity.PAGE: "pages",
    LedgerEntity.COMMENT: "comments",
    LedgerEntity.ATTACHMENT: "attachments",
    LedgerEntity.GRANT: "access_grants",
    LedgerEntity.VERSION: "page_versions",
}


async def preflight(session: AsyncSession, run: ConfluenceRun) -> RollbackPreflight:
    records = list(
        (
            await session.execute(
                select(ConfluenceImportRecord).where(
                    ConfluenceImportRecord.run_id == run.id
                )
            )
        ).scalars()
    )
    by_entity: dict[str, int] = {}
    for record in records:
        by_entity[record.entity_type] = by_entity.get(record.entity_type, 0) + 1

    # Pages a person has edited since the run finished. Valid because imported
    # pages carry their ORIGINAL timestamp, so anything newer is a real edit.
    edited = 0
    if run.finished_at is not None:
        page_ids = [
            record.entity_id for record in records
            if record.entity_type == LedgerEntity.PAGE.value
        ]
        if page_ids:
            edited = int(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM pages WHERE id = ANY(CAST(:ids AS uuid[])) "
                        "AND updated_at > :cutoff"
                    ),
                    {"ids": page_ids, "cutoff": run.finished_at},
                )
                or 0
            )
    return RollbackPreflight(
        total=len(records), by_entity=by_entity, edited_since=edited
    )


async def execute(
    session: AsyncSession,
    run: ConfluenceRun,
    *,
    include_containers: bool = False,
    skip_edited: bool = True,
) -> dict:
    """Undo, children first. Keeping the SPACE by default is the useful behaviour:
    it lets you fix a mapping and re-import without rebuilding the space."""
    records = list(
        (
            await session.execute(
                select(ConfluenceImportRecord).where(
                    ConfluenceImportRecord.run_id == run.id
                )
            )
        ).scalars()
    )
    order = {entity: index for index, entity in enumerate(UNDO_ORDER)}
    records.sort(
        key=lambda r: (order.get(LedgerEntity(r.entity_type), 99), -r.id)
    )

    protected: set[str] = set()
    if skip_edited and run.finished_at is not None:
        rows = await session.execute(
            text("SELECT id::text FROM pages WHERE updated_at > :cutoff"),
            {"cutoff": run.finished_at},
        )
        protected = {row[0] for row in rows}

    counts = {"removed": 0, "restored": 0, "skipped": 0}
    for record in records:
        entity = LedgerEntity(record.entity_type)
        if entity in CONTAINER_ENTITIES and not include_containers:
            counts["skipped"] += 1
            continue
        if entity is LedgerEntity.PAGE and record.entity_id in protected:
            counts["skipped"] += 1
            continue
        try:
            async with session.begin_nested():
                if record.action == LedgerAction.CREATED.value:
                    await _delete(session, entity, record.entity_id)
                    counts["removed"] += 1
                else:
                    await _restore(session, entity, record)
                    counts["restored"] += 1
        except Exception:  # noqa: BLE001 — one row must not abort the rest
            logger.warning(
                "rollback of %s %s failed", record.entity_type, record.entity_id,
                exc_info=True,
            )
            counts["skipped"] += 1

    await session.execute(
        delete(ConfluencePendingRef).where(ConfluencePendingRef.run_id == run.id)
    )
    await session.execute(
        delete(ConfluenceImportRecord).where(ConfluenceImportRecord.run_id == run.id)
    )
    await session.commit()
    return counts


async def _delete(session: AsyncSession, entity: LedgerEntity, entity_id: str) -> None:
    table = _TABLES.get(entity)
    if table is None:
        return
    await session.execute(
        text(f"DELETE FROM {table} WHERE id = CAST(:id AS uuid)"), {"id": entity_id}
    )


async def _restore(
    session: AsyncSession, entity: LedgerEntity, record: ConfluenceImportRecord
) -> None:
    table = _TABLES.get(entity)
    if table is None or not record.before:
        return
    assignments = ", ".join(f"{column} = :{column}" for column in record.before)
    await session.execute(
        text(f"UPDATE {table} SET {assignments} WHERE id = CAST(:__id AS uuid)"),
        {**record.before, "__id": record.entity_id},
    )
