"""Undoing an import (spec 100).

Spec 90 had no way back: a bad import was unwound with hand-written SQL, which is
literally what its own tests did. Here every write is in the ledger, and rollback
replays it in reverse — deleting what was created, restoring the before-image of
what was updated.

Two scopes, because they are different decisions: undo the ISSUES and keep the
project and its fields (so you can fix the mapping and re-import), or undo
everything including the provisioned schema.

A pre-flight reports anything a human has touched since the import, so destroying
someone's later edits is a choice rather than a surprise.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete as sa_delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items.models import WorkItem

from . import ledger
from .models import JiraImportRecord, JiraPendingRef, JiraRun
from .types import LedgerAction, LedgerEntity, Problem, ProblemKind

logger = logging.getLogger(__name__)

# The table each ledger entity lives in. A plain DELETE rather than each module's
# service: rollback is an administrative undo of rows this import created, and
# routing it through `delete_item` would re-run permission checks, refuse while
# children exist, and emit a deletion event for work that never really happened.
_TABLES: dict[LedgerEntity, str] = {
    LedgerEntity.WEB_LINK: "item_web_links",
    LedgerEntity.ITEM_LINK: "item_links",
    LedgerEntity.ATTACHMENT: "attachments",
    LedgerEntity.WORKLOG: "worklogs",
    LedgerEntity.COMMENT: "comments",
    LedgerEntity.ITEM: "work_items",
    LedgerEntity.CYCLE: "cycles",
    LedgerEntity.RELEASE: "releases",
    LedgerEntity.TEAM: "teams",
    LedgerEntity.ISSUE_TYPE: "issue_types",
    LedgerEntity.STATE: "states",
    LedgerEntity.FIELD: "field_definitions",
    LedgerEntity.LINK_TYPE: "item_link_types",
    LedgerEntity.USER: "users",
    LedgerEntity.PROJECT: "projects",
}


@dataclass
class Preflight:
    """What a rollback would do, and what it would destroy that it did not create."""

    total: int = 0
    by_entity: dict[str, int] = field(default_factory=dict)
    edited_since: list[str] = field(default_factory=list)  # Radd keys touched by a human


@dataclass
class RollbackResult:
    undone: int = 0
    restored: int = 0
    skipped: int = 0
    problems: list[Problem] = field(default_factory=list)


async def preflight(session: AsyncSession, run: JiraRun) -> Preflight:
    """What is in the ledger, plus which imported items have been edited since.

    "Edited since" is `updated_at` later than the run finished. An imported item
    is stamped with its ORIGINAL Jira timestamp, so anything later is genuinely a
    change made in Radd afterwards — work a rollback would throw away.
    """
    out = Preflight()
    records = await ledger.records_for(session, run.id)
    out.total = len(records)
    for record in records:
        out.by_entity[record.entity_type] = out.by_entity.get(record.entity_type, 0) + 1

    item_ids = [
        uuid.UUID(r.entity_id)
        for r in records
        if r.entity_type == LedgerEntity.ITEM.value and _is_uuid(r.entity_id)
    ]
    if item_ids and run.finished_at is not None:
        result = await session.execute(
            select(WorkItem).where(
                WorkItem.id.in_(item_ids), WorkItem.updated_at > run.finished_at
            )
        )
        out.edited_since = [str(item.id) for item in result.scalars()]
    return out


async def execute(
    session: AsyncSession,
    run: JiraRun,
    *,
    include_schema: bool,
    skip_edited: bool,
) -> RollbackResult:
    """Undo the run, newest write first.

    `include_schema=False` keeps the project, fields, states, types and users, so
    the mapping can be corrected and re-imported without provisioning again.
    `skip_edited=True` leaves alone any item a human has changed since.
    """
    result = RollbackResult()
    protected: set[str] = set()
    if skip_edited:
        protected = set((await preflight(session, run)).edited_since)

    records = await ledger.records_for(session, run.id)
    # Reverse dependency order within the reverse-time order: children before
    # parents, content before the schema it points at.
    order = {entity: index for index, entity in enumerate(ledger.UNDO_ORDER)}
    records.sort(key=lambda r: (order.get(_entity(r), 99), -r.id))

    for record in records:
        entity = _entity(record)
        if entity is None:
            continue
        if not include_schema and record.is_schema:
            result.skipped += 1
            continue
        if record.entity_id in protected:
            result.skipped += 1
            result.problems.append(
                Problem(
                    kind=ProblemKind.ROLLBACK_BLOCKED,
                    message="edited since the import — left alone",
                    subject=record.subject or record.entity_id,
                )
            )
            continue
        try:
            # A SAVEPOINT per row: one stubborn delete (a foreign key we did not
            # anticipate) must not poison the transaction and abort every
            # remaining undo.
            async with session.begin_nested():
                if LedgerAction(record.action) is LedgerAction.CREATED:
                    await _delete(session, entity, record.entity_id)
                    result.undone += 1
                else:
                    await _restore(session, entity, record)
                    result.restored += 1
        except Exception as exc:  # noqa: BLE001 — one stubborn row must not stop the undo
            result.skipped += 1
            result.problems.append(
                Problem(
                    kind=ProblemKind.ROLLBACK_BLOCKED,
                    message="could not be undone",
                    subject=record.subject or record.entity_id,
                    detail=str(exc),
                )
            )
    # Pending refs belong to the run that recorded them; with its items gone they
    # would point at nothing.
    await session.execute(sa_delete(JiraPendingRef).where(JiraPendingRef.run_id == run.id))
    await session.execute(
        sa_delete(JiraImportRecord).where(JiraImportRecord.run_id == run.id)
    )
    await session.flush()
    return result


async def _delete(session: AsyncSession, entity: LedgerEntity, entity_id: str) -> None:
    typed = _typed(entity_id)
    if entity is LedgerEntity.PROJECT:
        # Items are undone before the project, so anything still here was
        # deliberately KEPT — an issue somebody edited after the import. Removing
        # the project would delete it anyway and silently defeat that protection.
        remaining = (
            await session.execute(
                text("SELECT count(*) FROM work_items WHERE project_id = :id"), {"id": typed}
            )
        ).scalar() or 0
        if remaining:
            raise RuntimeError(
                f"{remaining} issue(s) were kept (edited since the import), so the "
                "project was kept too"
            )
        # RADD-1174: the projects module owns the teardown. This used to walk
        # `registries.project_purge_tables()` itself, which covered the tables
        # a `DELETE … WHERE project_id` can reach and nothing else — comments,
        # attachments, scoped settings and the fields scoped only to this
        # project all survived an undo. Now an import's undo is the same
        # deletion the admin surface performs, blockers included.
        from radd.modules.projects import service as projects_service

        project = await projects_service.get_project(session, typed)
        await projects_service.delete_project(session, project)
        return
    await session.execute(
        text(f"DELETE FROM {_TABLES[entity]} WHERE id = :id"), {"id": typed}
    )


async def _restore(
    session: AsyncSession, entity: LedgerEntity, record: JiraImportRecord
) -> None:
    """Put back exactly the columns the import changed — nothing else."""
    before = record.before or {}
    if not before:
        return
    # A JSONB column (a field's `options`) needs an explicit cast, or psycopg
    # adapts a Python list to a Postgres ARRAY. CAST(...) rather than `::jsonb`:
    # SQLAlchemy's `text()` parses `:name::jsonb` as a bind parameter and breaks.
    assignments = ", ".join(
        f"{column} = CAST(:{column} AS jsonb)"
        if isinstance(value, (list, dict))
        else f"{column} = :{column}"
        for column, value in before.items()
    )
    params: dict[str, object] = {
        column: json.dumps(value) if isinstance(value, (list, dict)) else value
        for column, value in before.items()
    }
    params["id"] = _typed(record.entity_id)
    await session.execute(
        text(f"UPDATE {_TABLES[entity]} SET {assignments} WHERE id = :id"), params
    )


def _entity(record: JiraImportRecord) -> LedgerEntity | None:
    try:
        return LedgerEntity(record.entity_type)
    except ValueError:
        return None


def _typed(entity_id: str) -> object:
    return uuid.UUID(entity_id) if _is_uuid(entity_id) else entity_id


def _is_uuid(raw: str) -> bool:
    try:
        uuid.UUID(raw)
        return True
    except (ValueError, AttributeError):
        return False
