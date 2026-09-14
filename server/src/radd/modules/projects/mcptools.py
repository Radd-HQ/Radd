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


async def _update_project(session: AsyncSession, actor: Any, args: Mapping[str, Any]) -> Any:
    """RADD-1009. Kernel-enforced: the dispatcher already required
    `project.manage` on the `project` key before this ran, so the handler only
    resolves + writes. `ProjectUpdate` validates (blank name, lengths)."""
    from . import service as projects_service
    from .schemas import ProjectUpdate

    project = await projects_service.get_by_key(session, str(args["project"]))
    fields = {k: args[k] for k in ("name", "description") if k in args}
    await projects_service.update_project(
        session, project, ProjectUpdate(**fields), actor_id=actor.id
    )
    return {
        "id": str(project.id),
        "key": project.key,
        "name": project.name,
        "description": project.description,
    }


async def _delete_project(session: AsyncSession, actor: Any, args: Mapping[str, Any]) -> Any:
    """RADD-1174. Kernel-enforced on the GLOBAL `project.delete` atom (no
    `project_param`: the atom is not held per project), so the catalog hides
    the tool from any key that lacks it and the dispatcher refuses a call
    regardless. A blocker comes back as the 409 reason, like every refusal."""
    from . import service as projects_service

    project = await projects_service.get_by_key(session, str(args["project"]))
    key, name = project.key, project.name
    inspection = await projects_service.delete_project(session, project, actor_id=actor.id)
    return {"deleted": {"key": key, "name": name}, "removed": dict(inspection.counts)}


LIST_PROJECTS = McpToolSpec(
    name="list_projects",
    description="List every project on this Radd instance.",
    input_schema=object_schema({}),
    handler=_list_projects,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

UPDATE_PROJECT = McpToolSpec(
    name="update_project",
    description=(
        "Rename a project or set its description. The key cannot change — item "
        "keys derive from it. Requires project.manage on that project."
    ),
    input_schema=object_schema(
        {
            "project": {"type": "string", "description": "Project key, e.g. TD."},
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "description": {"type": "string", "maxLength": 4000},
        },
        ["project"],
    ),
    handler=_update_project,
    permission=Permission.PROJECT_MANAGE,
    project_scoped=True,
    project_param="project",
)

DELETE_PROJECT = McpToolSpec(
    name="delete_project",
    description=(
        "PERMANENTLY delete a project and everything in it: issues, comments, "
        "attachments, worklogs, releases, views, forms, states. Cannot be undone. "
        "Refused (409) while a mail source or rule still routes into it. Requires "
        "the global project.delete permission."
    ),
    input_schema=object_schema(
        {"project": {"type": "string", "description": "Project key, e.g. TD."}},
        ["project"],
    ),
    handler=_delete_project,
    permission=Permission.PROJECT_DELETE,
)

MCP_TOOLS = (LIST_PROJECTS, UPDATE_PROJECT, DELETE_PROJECT)
