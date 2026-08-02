"""What each tool needs, and how the catalog narrows to the caller (spec 114).

`tools/list` stops being a constant. For each tool we know the permission it
demands and whether that permission is checked per project; the caller's own
resolution (already intersected with the key's scope by spec 113) answers where
they hold it. A tool with nowhere to run does not appear, and a tool that does
carries an ENUM of the projects it may run in — so an agent cannot even name a
project it may not write to.

Hiding is presentation, not enforcement: every tool still calls `authz.require`,
and a tool invoked without being listed fails exactly as it always did.

Plugin-contributed tools (RADD-640) carry their requirement ON the spec, so the
registry path is annotated by construction — which is what let the old
show-unannotated-tools fallback become a hide-and-log: a tool in neither
REQUIREMENTS nor the kernel registry is a wiring bug, not a contribution.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .types import McpTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolRequirement:
    """`permission=None` means the tool is available to anyone who can
    authenticate."""

    permission: Permission | None = None
    project_scoped: bool = False
    #: The input property naming a project, rewritten to an enum of the projects
    #: where `permission` actually holds.
    project_param: str | None = None


REQUIREMENTS: dict[str, ToolRequirement] = {
    # "What can I see" — item.read SOMEWHERE, exactly the handler's gate (RADD-672).
    McpTool.LIST_PROJECTS.value: ToolRequirement(Permission.ITEM_READ, project_scoped=True),
    McpTool.SEARCH_ITEMS.value: ToolRequirement(Permission.ITEM_READ, project_scoped=True),
    McpTool.FIND_ITEMS.value: ToolRequirement(Permission.ITEM_READ, project_scoped=True),
    McpTool.GET_ITEM.value: ToolRequirement(Permission.ITEM_READ, project_scoped=True),
    McpTool.CREATE_ITEM.value: ToolRequirement(
        Permission.ITEM_CREATE, project_scoped=True, project_param="project_key"
    ),
    McpTool.UPDATE_ITEM.value: ToolRequirement(Permission.ITEM_UPDATE, project_scoped=True),
    McpTool.COMMENT_ITEM.value: ToolRequirement(Permission.COMMENT_WRITE, project_scoped=True),
    # RADD-739: the same atom `items/service/links.py` already requires on the
    # SOURCE item's project, so enforcement is inherited rather than re-derived.
    McpTool.LINK_ITEMS.value: ToolRequirement(Permission.ITEM_UPDATE, project_scoped=True),
    McpTool.UNLINK_ITEMS.value: ToolRequirement(Permission.ITEM_UPDATE, project_scoped=True),
    McpTool.GET_PAGE.value: ToolRequirement(Permission.PAGE_READ),
    McpTool.SEARCH_PAGES.value: ToolRequirement(Permission.PAGE_READ),
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
    # Same atom as POST /releases/{id}/sweep (spec 112).
    McpTool.SWEEP_RELEASE.value: ToolRequirement(
        Permission.RELEASE_UPDATE, project_scoped=True, project_param="project_key"
    ),
    McpTool.SET_ITEM_RELEASE.value: ToolRequirement(Permission.ITEM_UPDATE, project_scoped=True),
    McpTool.LIST_USERS.value: ToolRequirement(Permission.USER_MANAGE),
    McpTool.LIST_SERVICE_ACCOUNTS.value: ToolRequirement(Permission.GLOBAL_MANAGE),
    McpTool.CREATE_SERVICE_ACCOUNT.value: ToolRequirement(Permission.SERVICE_ACCOUNT_CREATE),
}


def requirement_for(name: str) -> ToolRequirement | None:
    """The requirement for a tool by name: the builtin table first, else the
    kernel registry (a plugin's spec IS its annotation, RADD-640). None means
    the name is in neither — a wiring bug the caller should treat as hidden."""
    builtin = REQUIREMENTS.get(name)
    if builtin is not None:
        return builtin
    from radd.kernel import registries  # deferred: keep the kernel import lazy

    spec = registries.mcp_tools.get(name)
    if spec is None:
        return None
    return ToolRequirement(
        # Plugin atoms are registered KEYS, not Permission members; the sets they
        # are checked against hold plain strings (combine_permissions), so a str
        # atom participates in every membership test a builtin does.
        permission=cast(Permission, spec.permission) if spec.permission else None,
        project_scoped=spec.project_scoped,
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

    visible: list[dict[str, Any]] = []
    for tool in catalog:
        requirement = requirement_for(tool["name"])
        if requirement is None:
            # In neither the builtin table nor the kernel registry: a wiring bug.
            # Since RADD-640 every legitimate tool is annotated by construction,
            # so hide it — advertising a tool whose requirement nobody can state
            # is how an unfiltered tool would slip out.
            logger.warning("mcp tool %r has no requirement; hiding it", tool["name"])
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
