"""Small board directories, limited to keys from the authorized aggregate.

No item hydration to discover a column name. Epic keys have already passed the
readable-ancestor guard in grouped_items; do not call this with arbitrary IDs.
"""

import uuid

from .slq.catalog import SlqField
from sqlalchemy import select

from radd.modules.auth.models import User
from radd.modules.teams.models import Team
from radd.modules.projects.models import Project
from .grouped_axes import HIDDEN_EPIC_BUCKET
from .models import WorkItem


#: What the hidden-epic bucket is called (RADD-1491); the SPA's `groupByEpic`
#: uses the same words for rows it buckets client-side.
HIDDEN_EPIC_LABEL = "Epic you cannot see"


async def board_labels(session, axis, totals):
    labels = {key: key for key in totals}
    refs = {}
    ids = (
        [uuid.UUID(key) for key in totals if not key.startswith("__")]
        if axis in ("assignee", "team", "epic", "project")
        else []
    )
    if axis in ("assignee", "team"):
        model = User if axis == SlqField.ASSIGNEE else Team
        for key, name in (
            await session.execute(select(model.id, model.name).where(model.id.in_(ids)))
        ).all():
            labels[str(key)] = name
    elif axis == SlqField.PROJECT:
        for key, project_key, name in (
            await session.execute(
                select(Project.id, Project.key, Project.name).where(Project.id.in_(ids))
            )
        ).all():
            labels[str(key)] = f"{project_key} · {name}"
    elif axis == SlqField.EPIC:
        if HIDDEN_EPIC_BUCKET in totals:
            labels[HIDDEN_EPIC_BUCKET] = HIDDEN_EPIC_LABEL
        rows = (
            await session.execute(
                select(WorkItem.id, Project.key, WorkItem.number, WorkItem.title, WorkItem.kind)
                .join(Project, Project.id == WorkItem.project_id)
                .where(WorkItem.id.in_(ids))
            )
        ).all()
        for id_, project_key, number, title, kind in rows:
            key = f"{project_key}-{number}"
            labels[str(id_)] = f"{key} · {title}"
            refs[str(id_)] = {"id": str(id_), "key": key, "title": title, "kind": kind}
    return labels, refs
