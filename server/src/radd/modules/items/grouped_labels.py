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
from .models import WorkItem


async def board_labels(session, axis, totals):
    labels = {key: key for key in totals}
    refs = {}
    ids = (
        [uuid.UUID(key) for key in totals if not key.startswith("__")]
        if axis in ("assignee", "team", "epic")
        else []
    )
    if axis in ("assignee", "team"):
        model = User if axis == SlqField.ASSIGNEE else Team
        for key, name in (
            await session.execute(select(model.id, model.name).where(model.id.in_(ids)))
        ).all():
            labels[str(key)] = name
    elif axis == SlqField.EPIC:
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
