"""What each tool needs, and how the catalog narrows to the caller (spec 114).

`tools/list` stops being a constant. For each tool we know the permission it
demands and whether that permission is checked per project; the caller's own
resolution (already intersected with the key's scope by spec 113) answers where
they hold it. A tool with nowhere to run does not appear, and a tool that does
carries an ENUM of the projects it may run in — so an agent cannot even name a
project it may not write to.

Hiding is presentation, not enforcement: every tool still calls `authz.require`,
and a tool invoked without being listed fails exactly as it always did.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .types import McpTool


@dataclass(frozen=True)
class ToolRequirement:
    """`permission=None` means the tool is available to anyone who can
    authenticate (list_projects answers "what can I see", which is already
    per-actor)."""

    permission: Permission | None = None
    project_scoped: bool = False
    #: The input property naming a project, rewritten to an enum of the projects
    #: where `permission` actually holds.
    project_param: str | None = None


REQUIREMENTS: dict[str, ToolRequirement] = {
    McpTool.LIST_PROJECTS.value: ToolRequirement(),
    McpTool.SEARCH_ITEMS.value: ToolRequirement(Permission.ITEM_READ, project_scoped=True),
    McpTool.FIND_ITEMS.value: ToolRequirement(Permission.ITEM_READ, project_scoped=True),
    McpTool.GET_ITEM.value: ToolRequirement(Permission.ITEM_READ, project_scoped=True),
    McpTool.CREATE_ITEM.value: ToolRequirement(
        Permission.ITEM_CREATE, project_scoped=True, project_param="project_key"
    ),
    McpTool.UPDATE_ITEM.value: ToolRequirement(Permission.ITEM_UPDATE, project_scoped=True),
    McpTool.COMMENT_ITEM.value: ToolRequirement(Permission.COMMENT_WRITE, project_scoped=True),
    McpTool.GET_DOC_PAGE.value: ToolRequirement(Permission.DOC_READ),
    McpTool.SEARCH_DOCS.value: ToolRequirement(Permission.DOC_READ),
    # --- spec 114 families ---
    McpTool.GET_ALLOWED_TRANSITIONS.value: ToolRequirement(
        Permission.ITEM_READ, project_scoped=True
    ),
    McpTool.TRANSITION_ITEM.value: ToolRequirement(Permission.ITEM_UPDATE, project_scoped=True),
    McpTool.LOG_WORK.value: ToolRequirement(Permission.WORKLOG_WRITE, project_scoped=True),
    McpTool.LIST_WORKLOGS.value: ToolRequirement(Permission.WORKLOG_WRITE, project_scoped=True),
    McpTool.LIST_RELEASES.value: ToolRequirement(
        Permission.ITEM_READ, project_scoped=True, project_param="project_key"
    ),
    McpTool.CREATE_RELEASE.value: ToolRequirement(
        Permission.RELEASE_CREATE, project_scoped=True, project_param="project_key"
    ),
    McpTool.SET_ITEM_RELEASE.value: ToolRequirement(Permission.ITEM_UPDATE, project_scoped=True),
    McpTool.LIST_USERS.value: ToolRequirement(Permission.USER_MANAGE),
    McpTool.LIST_SERVICE_ACCOUNTS.value: ToolRequirement(Permission.GLOBAL_MANAGE),
    McpTool.CREATE_SERVICE_ACCOUNT.value: ToolRequirement(Permission.SERVICE_ACCOUNT_CREATE),
}


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

    visible: list[dict[str, Any]] = []
    for tool in catalog:
        requirement = REQUIREMENTS.get(tool["name"])
        if requirement is None:
            # An unannotated tool (a plugin's, before it declares one) stays
            # visible: silently hiding a contribution would be worse than showing
            # one the caller may not run.
            visible.append(tool)
            continue
        if requirement.permission is None:
            visible.append(tool)
            continue
        if not requirement.project_scoped:
            if requirement.permission in global_permissions:
                visible.append(tool)
            continue
        allowed = [
            keys_by_id[pid]
            for pid, permissions in per_project.items()
            if requirement.permission in permissions
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
