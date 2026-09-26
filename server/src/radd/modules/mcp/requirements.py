"""What each tool needs, and how the catalog narrows to the caller (spec 114).

Every `McpToolSpec` carries its requirement (the spec IS the annotation, RADD-640). A tool
with nowhere to run is hidden; a project-scoped one carries an ENUM of the projects it may
run in. Hiding is presentation, not enforcement — every call still passes `authz.require`.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.kernel import registries
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolRequirement:
    """`permission=None` means the tool is available to anyone who can
    authenticate."""

    permission: Permission | None = None
    project_scoped: bool = False
    space_scoped: bool = False
    #: The input property naming a project, rewritten to an enum of the projects
    #: where `permission` actually holds.
    project_param: str | None = None


def requirement_for(name: str) -> ToolRequirement | None:
    """The requirement read off the tool's registered spec; None = unregistered (hide it)."""
    spec = registries.mcp_tools.get(name)
    if spec is None:
        return None
    return ToolRequirement(
        # Plugin atoms are plain str KEYS; the permission sets hold strings, so they test alike.
        permission=cast(Permission, spec.permission) if spec.permission else None,
        project_scoped=spec.project_scoped,
        space_scoped=spec.space_scoped,
        project_param=spec.project_param or None,
    )


async def _project_permissions(
    session: AsyncSession, user: User
) -> tuple[list[Project], dict[uuid.UUID, frozenset[Permission]]]:
    projects = await projects_service.list_projects(session)
    if not projects:
        return [], {}
    return projects, await authz.permissions_for_projects(session, user, projects)


def _with_project_enum(tool: dict[str, Any], param: str, keys: Sequence[str]) -> dict[str, Any]:
    """Narrow the project parameter to the keys the caller may act in.

    Above `mcp_project_enum_max` the enum costs more context than it saves, so it
    degrades to a plain string that says how many projects are in play.
    """
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    if param not in properties:
        return tool
    prop = dict(properties[param])
    if len(keys) <= settings.mcp_project_enum_max:
        prop["enum"] = list(keys)
        prop["description"] = f"{prop.get('description', '').rstrip()} One of: {', '.join(keys)}."
    else:
        prop["description"] = (
            f"{prop.get('description', '').rstrip()} "
            f"{len(keys)} projects are available to this key."
        )
    return {
        **tool,
        "inputSchema": {**schema, "properties": {**properties, param: prop}},
    }


async def visible_catalog(
    session: AsyncSession, user: User | None, catalog: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The subset of `catalog` this principal can actually execute."""
    if user is None:
        return []
    projects, per_project = await _project_permissions(session, user)
    global_permissions = await authz.effective_permissions(session, user)
    keys_by_id = {project.id: project.key for project in projects}

    per_space = {}
    if any((requirement := requirement_for(tool["name"])) and requirement.space_scoped for tool in catalog):
        from radd.modules.pages.access import all_space_permissions
        per_space = await all_space_permissions(session, user)
    visible: list[dict[str, Any]] = []
    for tool in catalog:
        requirement = requirement_for(tool["name"])
        if requirement is None:
            # A wiring bug: a tool whose requirement nobody can state must not slip out unfiltered.
            logger.warning("mcp tool %r has no requirement; hiding it", tool["name"])
            continue
        if requirement.permission is None:
            visible.append(tool)
            continue
        # holds_base, not raw membership (RADD-825): a floor of item.read@OWN
        # still runs get_item — the relation resolvers narrow WHICH rows answer,
        # and hiding must match what the dispatcher's `authz.require` enforces.
        if requirement.space_scoped:
            if authz.holds_base(global_permissions, requirement.permission) or any(authz.holds_base(held, requirement.permission) for held in per_space.values()):
                visible.append(tool)
            continue
        if not requirement.project_scoped:
            if authz.holds_base(global_permissions, requirement.permission):
                visible.append(tool)
            continue
        allowed = [
            keys_by_id[pid]
            for pid, permissions in per_project.items()
            if authz.holds_base(permissions, requirement.permission)
        ]
        if not allowed:
            continue
        allowed.sort()
        visible.append(
            _with_project_enum(tool, requirement.project_param, allowed)
            if requirement.project_param
            else tool
        )
    return visible
