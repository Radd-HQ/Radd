"""The release MCP tools (specs 112/114, RADD-673/908), declared by their owner
(RADD-889).

Each handler carries its own `authz.require` on the resolved project, so
`kernel_enforced=False` and the spec's `permission`/`project_param` drive the
spec-114 caller filter (and its project-enum rewrite) only.

items is a weak dependency (it loads after releases), so `set_item_release`
reaches for it inside the handler, as does the pipeline (whose import chain
crosses into items too).
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
from radd.modules.projects.models import Project

from . import service as releases_service
from .models import Release
from .schemas import ReleaseCreate, ReleaseUpdate
from .types import ReleaseEntity, ReleaseStatus


async def _project_for(
    session: AsyncSession, actor: User, args: Mapping[str, Any], permission: Permission
) -> Project:
    project = await projects_service.get_by_key(session, str(args["project_key"]))
    await authz.require(session, actor, permission, project=project)
    return project


async def _release_for(
    session: AsyncSession, actor: User, args: Mapping[str, Any], permission: Permission
) -> tuple[Project, Release]:
    """Every tool addresses a release as (project_key, version) — the pair a
    person reads off the Releases page, never a row id."""
    project = await _project_for(session, actor, args, permission)
    release = await releases_service.resolve_release(session, project.id, str(args["version"]))
    if release is None:
        raise NotFoundError(ReleaseEntity.RELEASE, str(args["version"]))
    return project, release


def _summary(release: Release) -> dict[str, Any]:
    return {
        "id": str(release.id),
        "version": release.version,
        "name": release.name,
        "status": release.status,
        "released_at": release.released_at.isoformat() if release.released_at else None,
    }


def _full(release: Release) -> dict[str, Any]:
    return {**_summary(release), "description": release.description}


async def _list_releases(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await _project_for(session, actor, args, Permission.ITEM_READ)
    return [_summary(r) for r in await releases_service.list_releases(session, project.id)]


async def _get_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """The full record, notes included (RADD-908). A separate fetch rather than
    a wider list: forty releases each carrying multi-kilobyte notes is the wrong
    default shape for the list."""
    _project, release = await _release_for(session, actor, args, Permission.ITEM_READ)
    return _full(release)


async def _create_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    from . import pipeline as releases_pipeline

    project = await _project_for(session, actor, args, Permission.RELEASE_CREATE)
    values: dict[str, Any] = {}
    if args.get("status") is not None:  # RADD-673: a by-hand "released" is one call
        values["status"] = ReleaseStatus(str(args["status"]))
    release, moved = await releases_pipeline.create_release(
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
    return {**_summary(release), "items_shipped": moved}


async def _update_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Amend a release over MCP (RADD-908): the same atom and fields as
    PATCH /releases/{id}. Marking it released sweeps, like every other path."""
    from . import pipeline as releases_pipeline

    _project, release = await _release_for(session, actor, args, Permission.RELEASE_UPDATE)
    data = ReleaseUpdate(
        name=args.get("name"),
        version=args.get("new_version"),
        description=args.get("description"),
        status=ReleaseStatus(str(args["status"])) if args.get("status") is not None else None,
    )
    release, moved = await releases_pipeline.update_release(
        session, release.id, data, actor_id=actor.id
    )
    return {**_summary(release), "items_shipped": moved}


async def _sweep_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """The spec-112 pipeline step on demand (RADD-673): same atom and same
    service call as POST /releases/{id}/sweep."""
    from . import pipeline as releases_pipeline

    project, release = await _release_for(session, actor, args, Permission.RELEASE_UPDATE)
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
        match = await releases_service.resolve_release(session, current.project_id, str(version))
        if match is None:
            raise NotFoundError(ReleaseEntity.RELEASE, str(version))
        release_id = match.id
    read = await items_service.update_item(
        session, current.id, ItemUpdate(release_id=release_id), actor=actor
    )
    return receipt(read)


def _project_key_property() -> dict[str, Any]:
    return {"type": "string", "description": "Project key, e.g. TD."}


def _version_property(description: str = "Release version, e.g. 0.3.0.") -> dict[str, Any]:
    return {"type": "string", "description": description}


def _status_property() -> dict[str, Any]:
    return {
        "type": "string",
        "enum": [status.value for status in ReleaseStatus],
        "description": "planned or released — becoming released stamps released_at "
        "and sweeps every waiting item into the shipped state (spec 112).",
    }


LIST_RELEASES = McpToolSpec(
    name="list_releases",
    description="Releases/versions in a project, with their status (no notes — "
    "get_release carries those).",
    input_schema=object_schema({"project_key": _project_key_property()}, ["project_key"]),
    handler=_list_releases,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    project_param="project_key",
    kernel_enforced=False,
)

GET_RELEASE = McpToolSpec(
    name="get_release",
    description="One release in full, release notes included.",
    input_schema=object_schema(
        {"project_key": _project_key_property(), "version": _version_property()},
        ["project_key", "version"],
    ),
    handler=_get_release,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    project_param="project_key",
    kernel_enforced=False,
)

CREATE_RELEASE = McpToolSpec(
    name="create_release",
    description="Create a release/version in a project. Created as released, it "
    "sweeps the waiting items at once and reports how many shipped.",
    input_schema=object_schema(
        {
            "project_key": _project_key_property(),
            "version": _version_property(),
            "name": {"type": "string"},
            "description": {"type": "string", "description": "Release notes (markdown)."},
            "status": _status_property(),
        },
        ["project_key", "version"],
    ),
    handler=_create_release,
    permission=Permission.RELEASE_CREATE,
    project_scoped=True,
    project_param="project_key",
    kernel_enforced=False,
)

UPDATE_RELEASE = McpToolSpec(
    name="update_release",
    description="Amend a release's name, version, notes or status — including one "
    "a connector published, which create_release rightly refuses to duplicate.",
    input_schema=object_schema(
        {
            "project_key": _project_key_property(),
            "version": _version_property("The version to amend."),
            "name": {"type": "string"},
            "new_version": {"type": "string", "description": "Rename the version string."},
            "description": {"type": "string", "description": "Release notes (markdown)."},
            "status": _status_property(),
        },
        ["project_key", "version"],
    ),
    handler=_update_release,
    permission=Permission.RELEASE_UPDATE,
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
            "version": _version_property("Release version to sweep into."),
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

MCP_TOOLS = (
    LIST_RELEASES,
    GET_RELEASE,
    CREATE_RELEASE,
    UPDATE_RELEASE,
    SWEEP_RELEASE,
    SET_ITEM_RELEASE,
)
