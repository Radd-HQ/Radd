"""The plugin-contributed MCP tool (RADD-640). The kernel filters the catalog,
requires the atom on the named project BEFORE `_list` runs, and unregisters the
tool with the plugin — so this handler has no authz call, on purpose."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.sdk import McpToolSpec

from .models import Milestone


async def _list(session: AsyncSession, actor: Any, args: Mapping[str, Any]) -> Any:
    from radd.modules.projects import service as projects_service

    project = await projects_service.get_by_key(session, str(args["project_key"]).upper())
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
