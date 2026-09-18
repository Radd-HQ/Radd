"""The one shape every item-scoped event uses to say which item it is about
(RADD-922).

Before this there were fourteen shapes. The issue key was `key` on item and CSAT
events, `item_key` on SLA and page-link events, and absent from the other nine —
comments, worklogs, attachments, VCS links, web links, approvals, participants,
watchers. `project_id` appeared on two families out of fourteen. `item_id` was on
everything EXCEPT the item events themselves, which carry `id`.

The cost was not theoretical. `notify/consumer.py` resolved the key four
different ways — `payload["key"]`, `payload["item_key"]`, and two DB round-trips
for the events that carried neither. `googlechat/formatter.py` branched on the
spelling. `search/indexer.py` opened with `if "project_id" not in payload:
return`, a silent bail-out that made a missing field indistinguishable from an
item that should not be indexed.

So: **one function, one shape, nested under `item`.** Every item-scoped event
carries `payload["item"]`, and every consumer addresses `payload.item.<field>`.
That is also the vocabulary the automation tokens already use (`{{item.key}}`),
so the two stop being different languages for the same thing.

**Refs, not ids.** `state`, `project`, `team`, `assignee` are `{id, name}`
objects rather than bare uuids, because a payload exists to be READ — by a
webhook receiver, a chat message, an automation template. `{{payload.item.assignee.name}}`
is the point; `assignee_id` alone renders a uuid at someone and calls it a
notification.

The item events themselves nest their FULL read here instead of this compact
one — they are about the item, so they carry all of it. The keys below are the
floor, guaranteed on all 31 item-scoped event types and enforced by
`tests/test_event_payloads.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from itertools import batched
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team
from radd.modules.workflow.models import State

from ..models import WorkItem

#: The keys every `payload["item"]` carries. The contract test reads this, so a
#: new emitter cannot quietly ship a thinner ref.
REQUIRED_KEYS = ("id", "key", "title", "project", "state")


def _ref(row: Any) -> dict[str, str] | None:
    """`{id, name}` for a joined row, or None when the relation is unset."""
    return None if row is None else {"id": str(row.id), "name": row.name}


async def item_ref(session: AsyncSession, item_id: uuid.UUID | str) -> dict[str, Any] | None:
    """The canonical `payload["item"]` for one item, or None if it has gone.

    ONE query with outer joins. Emitters call this on a write path that has
    already touched the database, so the cost is a join rather than a round trip
    — and the alternative was consumers doing that round trip later, several
    times, per event.
    """
    row = (
        await session.execute(
            select(WorkItem, Project, State, Team, User)
            .join(Project, Project.id == WorkItem.project_id)
            .join(State, State.id == WorkItem.state_id)
            .outerjoin(Team, Team.id == WorkItem.team_id)
            .outerjoin(User, User.id == WorkItem.assignee_id)
            .where(WorkItem.id == item_id)
        )
    ).first()
    if row is None:
        return None
    item, project, state, team, assignee = row
    return ref_from(item, project, state, team=team, assignee=assignee)


async def item_refs(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Canonical event refs in bounded batches, without per-item round trips."""
    out = {}
    for batch in batched(dict.fromkeys(item_ids), 1000):
        rows = await session.execute(
            select(WorkItem, Project, State, Team, User)
            .join(Project, Project.id == WorkItem.project_id)
            .join(State, State.id == WorkItem.state_id)
            .outerjoin(Team, Team.id == WorkItem.team_id)
            .outerjoin(User, User.id == WorkItem.assignee_id)
            .where(WorkItem.id.in_(batch))
        )
        for item, project, state, team, assignee in rows:
            out[item.id] = ref_from(item, project, state, team=team, assignee=assignee)
    return out


def ref_from(
    item: WorkItem,
    project: Project,
    state: State | None = None,
    *,
    team: Team | None = None,
    assignee: User | None = None,
) -> dict[str, Any]:
    """The same shape from objects already in hand — the item services have them
    loaded and should not re-query for what they are holding."""
    return {
        "id": str(item.id),
        "key": f"{project.key}-{item.number}",
        "title": item.title,
        "kind": item.kind,
        "priority": item.priority,
        # `category` is what "did this just become done" tests, and the only
        # reason a state ref is not just a name.
        "state": (
            None
            if state is None
            else {"id": str(state.id), "name": state.name, "category": state.category}
        ),
        "project": {"id": str(project.id), "key": project.key, "name": project.name},
        "team": _ref(team),
        "assignee": _ref(assignee),
    }
