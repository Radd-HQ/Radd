"""Mirrored worklogs — time logged at a VCS host, copied here (RADD-1258).

A connector hands over the CURRENT entries for one ref (MR/PR), each with the
provider's entry id; this module makes the item's worklogs match — create,
update, delete. Keyed by (source, external_id) under a partial unique index, so
redeliveries and backfills land on one row. Deletion is scoped by
`external_scope` (the ref), never by item: one item carries time from several
MRs. A mirrored row is read-only here (`service.authorize_mutation` refuses).
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import changes

from . import enablement, service
from .models import Worklog
from .types import WorklogEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalEntry:
    """One time entry as the provider reports it, already resolved to Radd ids.

    `author_id` is the RADD user the provider's user was matched to — the
    connector (via `vcs.timemirror`) does that matching; an entry whose author
    cannot be matched never reaches this module.
    """

    external_id: str
    item_id: uuid.UUID
    author_id: uuid.UUID
    seconds: int
    worked_on: date
    note: str = ""
    category_id: uuid.UUID | None = None


@dataclass
class ReconcileReport:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    #: Items whose project has time logging OFF — nothing written for them.
    skipped_disabled: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "unchanged": self.unchanged,
            "skipped_disabled": self.skipped_disabled,
        }


async def _existing_for_scope(
    session: AsyncSession, source: str, scope: str
) -> dict[str, Worklog]:
    rows = await session.execute(
        select(Worklog).where(
            Worklog.external_source == source, Worklog.external_scope == scope
        )
    )
    return {row.external_id: row for row in rows.scalars()}


async def _find_by_external(session: AsyncSession, source: str, external_id: str) -> Worklog | None:
    return await session.scalar(
        select(Worklog).where(
            Worklog.external_source == source, Worklog.external_id == external_id
        )
    )


async def item_enabled(session: AsyncSession, item_id: uuid.UUID) -> bool:
    """Whether the item's project logs time — the gate a mirror honours."""
    _item, project = await service._project_for_item(session, item_id)
    return await enablement.is_enabled(session, project.id)


async def _enabled_for_item(session: AsyncSession, item_id: uuid.UUID, cache: dict) -> bool:
    if item_id not in cache:
        cache[item_id] = await item_enabled(session, item_id)
    return cache[item_id]


async def upsert_external_worklog(
    session: AsyncSession, *, source: str, scope: str, entry: ExternalEntry
) -> tuple[Worklog, str]:
    """Create or update the mirror of ONE source entry -> (row, created|updated|unchanged).
    Inserts under a SAVEPOINT, so two racing deliveries' unique-index refusal
    becomes the update it should have been (the `vcs.upsert_vcs_link` idiom)."""
    existing = await _find_by_external(session, source, entry.external_id)
    if existing is None:
        worklog = Worklog(
            item_id=entry.item_id,
            author_id=entry.author_id,
            category_id=entry.category_id,
            worked_on=entry.worked_on,
            time_spent_seconds=entry.seconds,
            note=entry.note,
            external_source=source,
            external_scope=scope,
            external_id=entry.external_id,
        )
        try:
            async with session.begin_nested():
                session.add(worklog)
                await session.flush()
        except IntegrityError:
            existing = await _find_by_external(session, source, entry.external_id)
            if existing is None:
                raise
        else:
            await service._emit(session, WorklogEvent.CREATED, worklog, entry.author_id)
            return worklog, "created"

    before = await service._worklog_audit_state(session, existing)
    moved = existing.item_id != entry.item_id
    existing.item_id = entry.item_id
    existing.author_id = entry.author_id
    existing.category_id = entry.category_id
    existing.worked_on = entry.worked_on
    existing.time_spent_seconds = entry.seconds
    existing.note = entry.note
    existing.external_scope = scope
    await session.flush()
    diff = changes.diff(before, await service._worklog_audit_state(session, existing), hidden=("note",))
    if not diff and not moved:
        return existing, "unchanged"
    await service._emit(
        session, WorklogEvent.UPDATED, existing, entry.author_id, diff=diff or None,
    )
    return existing, "updated"


async def reconcile_external_worklogs(
    session: AsyncSession,
    *,
    source: str,
    scope: str,
    entries: Sequence[ExternalEntry],
    id_prefix: str | None = None,
) -> ReconcileReport:
    """Make the mirrored worklogs for (`source`, `scope`) equal `entries`: upsert each
    by external id, delete the scope's rows not among them. Items whose project has
    logging disabled are skipped and counted, their existing rows left alone.
    `id_prefix` narrows the DELETION: a source reporting one comment at a time
    (GitHub's `/spend`) knows only THAT comment's entries."""
    report = ReconcileReport()
    enabled_cache: dict[uuid.UUID, bool] = {}
    keep: set[str] = set()

    for entry in entries:
        if not await _enabled_for_item(session, entry.item_id, enabled_cache):
            report.skipped_disabled += 1
            keep.add(entry.external_id)  # never delete what we refused to touch
            continue
        _row, outcome = await upsert_external_worklog(session, source=source, scope=scope, entry=entry)
        keep.add(entry.external_id)
        setattr(report, outcome, getattr(report, outcome) + 1)

    for external_id, row in (await _existing_for_scope(session, source, scope)).items():
        if external_id in keep:
            continue
        if id_prefix is not None and not external_id.startswith(id_prefix):
            continue
        await _delete_row(session, row)
        report.deleted += 1

    logger.debug("external worklogs %s %s: %s", source, scope, report.as_dict())
    return report


async def _delete_row(session: AsyncSession, row: Worklog) -> None:
    actor = row.author_id
    await session.delete(row)
    await session.flush()
    await service._emit(session, WorklogEvent.DELETED, row, actor)


async def delete_external_worklogs(
    session: AsyncSession, *, source: str, scope: str, author_id: uuid.UUID | None = None
) -> int:
    """Remove every mirrored row under a scope — or only one author's (GitHub's
    `/unspend`, which says "forget MY time on this PR"). Returns the count."""
    deleted = 0
    for row in (await _existing_for_scope(session, source, scope)).values():
        if author_id is not None and row.author_id != author_id:
            continue
        await _delete_row(session, row)
        deleted += 1
    return deleted


async def parse_duration_text(session: AsyncSession, text: str) -> int:
    """`"1h30"` → seconds under the instance's hours-per-day, the same grammar the
    UI and MCP accept. Raises DurationError (a ValueError) on garbage."""
    return service._parse(text, await service.hours_per_day(session))
