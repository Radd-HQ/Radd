"""The plugin-contributed MCP tool (RADD-640) — proof the registry seam works.

One declaration and the kernel does the rest: `visible_catalog` hides the tool
from keys without item.read (and enum-rewrites `project_key`, spec 114), the
dispatcher requires the atom on the named project BEFORE `_list` runs, and
disabling the plugin unregisters the tool from catalog + dispatch together.
This handler contains no authz call on purpose — that absence is the feature.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.sdk import McpToolSpec

from .models import Milestone


async def _list(session: AsyncSession, actor: Any, args: Mapping[str, Any]) -> Any:
    from radd.modules.projects import service as projects_service

    key = str(args["project_key"]).upper()
    project = next(
        (p for p in await projects_service.list_projects(session) if p.key == key), None
    )
    if project is None:
        raise NotFoundError("project", key)
    rows = (
        (
            await session.execute(
                select(Milestone)
                .where(Milestone.project_id == project.id)
                .order_by(Milestone.due_on.asc().nulls_last(), Milestone.title.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "milestones": [
            {
                "id": str(m.id),
                "title": m.title,
                "description": m.description,
                "due_on": m.due_on.isoformat() if m.due_on else None,
                "status": m.status,
            }
            for m in rows
        ],
        "count": len(rows),
    }


LIST_MILESTONES = McpToolSpec(
    name="list_milestones",
    description="Milestones in a project, ordered by due date.",
    input_schema={
        "type": "object",
        "properties": {
            "project_key": {"type": "string", "description": "Project key, e.g. TD."}
        },
        "required": ["project_key"],
        "additionalProperties": False,
    },
    handler=_list,
    permission="item.read",  # entity reads are member reads (kernel.entities.authz_read_atom)
    project_scoped=True,
    project_param="project_key",
)
