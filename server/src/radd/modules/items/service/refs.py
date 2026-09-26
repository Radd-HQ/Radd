"""The one shape every item-scoped event uses to name its item (RADD-922).

Every item-scoped event carries `payload["item"]`, so consumers (notify, chat,
search, automation tokens like `{{item.key}}`) address `payload.item.<field>`
one way. Relations are `{id, name}` refs, not bare ids: a payload exists to be
read. Item events themselves carry the FULL read here; `REQUIRED_KEYS` is the
floor every emitter guarantees (tests/test_event_payloads.py).
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
    """The canonical `payload["item"]` for one item (one joined query), or None
    if it has gone."""
    refs = await item_refs(session, [item_id])
    return next(iter(refs.values()), None)


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
