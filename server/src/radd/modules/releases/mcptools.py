"""The release MCP tools (specs 112/114, RADD-673), declared by their owner
(RADD-889).

Handlers moved verbatim from mcp/tools.py — each carries its own
`authz.require` on the resolved project, exactly the pre-move enforcement, so
`kernel_enforced=False` and the spec's `permission`/`project_param` drive the
spec-114 caller filter (and its project-enum rewrite) only.

items is a weak dependency (it loads after releases), so `set_item_release`
reaches for it inside the handler, as does the sweep for the pipeline (whose
import chain crosses into items too).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.kernel.mcptools import object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.projects import service as projects_service

from . import service as releases_service
from .schemas import ReleaseCreate
from .types import ReleaseStatus


async def _list_releases(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await projects_service.get_by_key(session, str(args["project_key"]))
    await authz.require(session, actor, Permission.ITEM_READ, project=project)
    releases = await releases_service.list_releases(session, project.id)
    return [
        {"id": str(r.id), "version": r.version, "name": r.name, "status": r.status}
        for r in releases
    ]


async def _create_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await projects_service.get_by_key(session, str(args["project_key"]))
    await authz.require(session, actor, Permission.RELEASE_CREATE, project=project)
    values: dict[str, Any] = {}
    if args.get("status") is not None:  # RADD-673: a by-hand "released" is one call
        values["status"] = ReleaseStatus(str(args["status"]))
    release = await releases_service.create_release(
        session,
        ReleaseCreate(
            project_id=project.id,
            version=str(args["version"]),
            name=str(args.get("name") or args["version"]),
            description=str(args.get("description") or ""),
            **values,
        ),
        actor_id=actor.id,
    )
    return {"id": str(release.id), "version": release.version, "status": release.status}


async def _sweep_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """The spec-112 pipeline step, agent-reachable (RADD-673): same atom and same
    service call as POST /releases/{id}/sweep."""
    from . import pipeline as releases_pipeline

    project = await projects_service.get_by_key(session, str(args["project_key"]))
    await authz.require(session, actor, Permission.RELEASE_UPDATE, project=project)
    version = str(args["version"])
    releases = await releases_service.list_releases(session, project.id)
    release = next((r for r in releases if r.version == version), None)
    if release is None:
        raise NotFoundError("release", version)
    moved = await releases_pipeline.sweep(session, project, release)
    return {"release": release.version, "items_shipped": moved}


async def _set_item_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    from radd.modules.items import service as items_service
    from radd.modules.items.mcptools import receipt
    from radd.modules.items.schemas import ItemUpdate

    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    version = args.get("version")
    release_id = None
    if version:
        releases = await releases_service.list_releases(session, current.project_id)
        match = next((r for r in releases if r.version == str(version)), None)
        if match is None:
            raise NotFoundError("release", version)
        release_id = match.id
    read = await items_service.update_item(
        session, current.id, ItemUpdate(release_id=release_id), actor=actor
    )
    return receipt(read)


def _project_key_property() -> dict[str, Any]:
    return {"type": "string", "description": "Project key, e.g. TD."}


LIST_RELEASES = McpToolSpec(
    name="list_releases",
    description="Releases/versions in a project, with their status.",
    input_schema=object_schema({"project_key": _project_key_property()}, ["project_key"]),
    handler=_list_releases,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    project_param="project_key",
    kernel_enforced=False,
)

CREATE_RELEASE = McpToolSpec(
    name="create_release",
    description="Create a release/version in a project.",
    input_schema=object_schema(
        {
            "project_key": _project_key_property(),
            "version": {"type": "string", "description": "e.g. 0.3.0"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "status": {
                "type": "string",
                "enum": [status.value for status in ReleaseStatus],
                "description": "planned (default) or released — released stamps "
                "released_at server-side (RADD-673).",
            },
        },
        ["project_key", "version"],
    ),
    handler=_create_release,
    permission=Permission.RELEASE_CREATE,
    project_scoped=True,
    project_param="project_key",
    kernel_enforced=False,
)

# Same atom as POST /releases/{id}/sweep (spec 112).
SWEEP_RELEASE = McpToolSpec(
    name="sweep_release",
    description="Ship everything waiting (spec 112): move every item in the "
    "'waiting for release' state into the shipped state with this release set. "
    "The same operation a published Forgejo release performs, on demand.",
    input_schema=object_schema(
        {
            "project_key": _project_key_property(),
            "version": {"type": "string", "description": "Release version to sweep into."},
        },
        ["project_key", "version"],
    ),
    handler=_sweep_release,
    permission=Permission.RELEASE_UPDATE,
    project_scoped=True,
    project_param="project_key",
    kernel_enforced=False,
)

SET_ITEM_RELEASE = McpToolSpec(
    name="set_item_release",
    description="Set (or clear) the release an item ships in.",
    input_schema=object_schema(
        {
            "key": {"type": "string", "description": "Item key, e.g. TD-42."},
            "version": {
                "type": ["string", "null"],
                "description": "Release version; null clears it.",
            },
        },
        ["key"],
    ),
    handler=_set_item_release,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (LIST_RELEASES, CREATE_RELEASE, SWEEP_RELEASE, SET_ITEM_RELEASE)
