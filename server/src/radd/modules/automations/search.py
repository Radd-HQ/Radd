"""The SLQ source node (RADD-919): find issues and pass them downstream.

Every other node kind can only NARROW what the trigger handed it. A filter takes
a set and returns a subset; a gate routes; an action acts. So the reach of an
automation was bounded by the event: whatever the trigger named, plus nothing.
"When a release ships, comment on everything it fixed" and "every Monday, find
the stale bugs in DEV" had to be two different graphs, because only a SCHEDULE
trigger could produce a set — via a `query` param on the trigger itself, which is
the same feature wearing a disguise and available to exactly one trigger type.

A search node is that capability as a node: it runs an SLQ query and emits what
it found. It works under any trigger, several may appear in one graph, and the
query is visible on the canvas as a node rather than buried in a trigger's form.

Two decisions worth keeping:

* **REPLACE by default.** The common case reaches somewhere else entirely, and a
  silent union would make the result depend on whatever the trigger happened to
  carry — a search that returns 12 items would emit 13 after an item.updated and
  12 after a schedule tick, which is not a difference anyone would predict. ADD
  is offered for "this item AND everything like it".
* **It runs even on an empty packet.** A search PRODUCES items; requiring some
  first would make it useless on the itemless triggers it is most wanted on.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.items import slq
from radd.modules.items.models import WorkItem

from .types import SYSTEM_ACTOR_ID

logger = logging.getLogger(__name__)


async def all_definitions(session: AsyncSession) -> dict[str, FieldDefinition]:
    """key -> definition over the WHOLE field registry (oldest wins on dups) —
    the scope an unscoped query compiles against, since it belongs to no single
    project. Two projects with the same custom-field key resolve to the older
    definition, which is arbitrary but stable; scope the search to a project when
    that matters."""
    by_key: dict[str, FieldDefinition] = {}
    for definition in await fields.list_fields(session):
        by_key.setdefault(definition.key, definition)
    return by_key


async def find_items(
    session: AsyncSession,
    query: str,
    *,
    project_key: str = "",
    limit: int | None = None,
    label: str = "search",
) -> list[uuid.UUID]:
    """Active items matching `query`, in rank order, capped.

    The cap is `automation_schedule_max_items` — the same one the scheduler has
    always used, because "how many items may one automation run touch" is one
    question and two numbers would eventually disagree. Truncation is LOGGED: a
    run that hit the ceiling and one that genuinely matched 200 items are
    otherwise indistinguishable.

    An empty query returns nothing rather than everything. A half-filled form is
    the likeliest source of one, and "" meaning "every issue in the instance" is
    the most expensive possible reading of a mistake.
    """
    text = (query or "").strip()
    if not text:
        return []

    # Deferred: `planning` imports this module's siblings, and importing it at
    # module scope makes the automations package import order load-bearing.
    from .planning import _project_by_key, _project_definitions

    project = None
    if project_key.strip():
        project = await _project_by_key(session, project_key)
        if project is None:
            logger.warning("automations: %s: no project %r — no items", label, project_key)
            return []

    definitions = (
        await _project_definitions(session, project)
        if project is not None
        else await all_definitions(session)
    )
    compiled = await slq.compile_query(
        session,
        slq.parse(text),
        definitions_by_key=definitions,
        current_user_id=SYSTEM_ACTOR_ID,
        project_id=project.id if project is not None else None,
    )

    cap = min(limit or settings.automation_schedule_max_items, settings.automation_schedule_max_items)
    stmt = (
        select(WorkItem.id)
        .where(WorkItem.archived_at.is_(None))
        .order_by(WorkItem.rank)
        .limit(cap + 1)
    )
    if project is not None:
        stmt = stmt.where(WorkItem.project_id == project.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)

    ids = list((await session.execute(stmt)).scalars())
    if len(ids) > cap:
        logger.info("automations: %s matched over %d items — truncated to the cap", label, cap)
        ids = ids[:cap]
    return ids
