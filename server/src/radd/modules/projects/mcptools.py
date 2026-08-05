"""The `list_projects` MCP tool (spec 45), declared by its owner (RADD-889).

Moved verbatim from mcp/tools.py. The spec IS the spec-114 annotation
(`permission` drives the caller filter); enforcement stays the handler's own
`require_anywhere` gate, so `kernel_enforced=False` — a blanket global
`require` would re-refuse the scoped keys RADD-672 admitted.

auth is imported inside the handler: projects loads before auth (auth
depends_on projects), so a top-level reach would run during a partially
initialised boot.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel.mcptools import object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth.types import Permission


async def _list_projects(session: AsyncSession, actor: Any, args: Mapping[str, Any]) -> Any:
    from radd.modules.auth import authz

    from . import service as projects_service

    # Same gate as GET /projects (RADD-672): the projects where the caller holds
    # item.read anywhere — never a global-atom refusal for a scoped key.
    per_project = await authz.require_anywhere(
        session, actor, Permission.ITEM_READ, refuse_when_empty=True
    )
    projects = [p for p in await projects_service.list_projects(session) if p.id in per_project]
    return {
        "projects": [
            {"key": project.key, "name": project.name, "id": str(project.id)}
            for project in projects
        ]
    }


LIST_PROJECTS = McpToolSpec(
    name="list_projects",
    description="List every project on this Radd instance.",
    input_schema=object_schema({}),
    handler=_list_projects,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (LIST_PROJECTS,)
