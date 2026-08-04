"""MCP tool dispatch (spec 45): one handler per catalog tool.

Every handler resolves the PAT-authed actor's request through the ordinary
service/authz seams — an agent can do exactly what its principal may do,
nothing more. Domain failures (RaddError subclasses) bubble up for the router
to shape into `isError: true` results; the catalog itself lives in catalog.py,
pages-module feature detection in pages_bridge.py.
"""

import uuid
from collections.abc import Callable, Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.auth import authz, service as auth_service, service_accounts
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.auth.schemas import ServiceAccountCreate
from radd.modules.auth.types import AuthEntity
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentVisibility
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity, ItemKind, Priority
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemCreate, ItemLinkCreate, ItemRead, ItemUpdate
from radd.modules.releases import service as releases_service
from radd.modules.releases.schemas import ReleaseCreate
from radd.modules.releases.types import ReleaseStatus
from radd.modules.timelogging import service as timelogging_service, timesheet
from radd.modules.timelogging.slq import compile_worklog_query, parse as worklog_parse
from radd.modules.timelogging.schemas import WorklogCreate, WorklogUpdate
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow import transitions as workflow_transitions
from radd.modules.workflow.types import StateEntity
from radd.modules.projects import service as projects_service
from radd.modules.projects.types import ProjectEntity

from . import pages_bridge
from .catalog import build_catalog, live_catalog  # re-export: the module's tool surface
from .types import (
    PAGE_TOOLS,
    GET_ITEM_COMMENTS_TAIL,
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    WORKLOG_WINDOW_DAYS,
    McpTool,
)

__all__ = ["UnknownToolError", "build_catalog", "call_tool", "pages_available", "live_catalog"]

pages_available = pages_bridge.pages_available


class UnknownToolError(Exception):
    """tools/call named a tool outside the catalog -> JSON-RPC INVALID_PARAMS
    (deliberately NOT a RaddError: it must not become an isError tool result)."""

    def __init__(self, name: str):
        super().__init__(f"unknown tool '{name}'")


# --- shared resolvers ---


def _limit(args: Mapping[str, Any]) -> int:
    raw = args.get("limit", SEARCH_LIMIT_DEFAULT)
    return max(1, min(int(raw), SEARCH_LIMIT_MAX))


async def _project_by_key(session: AsyncSession, key: str):
    for project in await projects_service.list_projects(session):
        if project.key == key.upper():
            return project
    raise NotFoundError(ProjectEntity.PROJECT, key)


async def _state_id(session: AsyncSession, project_id: uuid.UUID, name: str) -> uuid.UUID:
    for state in await workflow_service.list_states(session, project_id):
        if state.name.lower() == name.lower():
            return state.id
    raise NotFoundError(StateEntity.STATE, name)


async def _user_id_by_email(session: AsyncSession, email: str) -> uuid.UUID:
    user = await auth_service.get_user_by_email(session, email)
    if user is None:
        raise NotFoundError(AuthEntity.USER, email)
    return user.id


# --- name -> id resolvers (RADD-673: names in, ids resolved server-side) ---


async def _type_id(session: AsyncSession, project_id: uuid.UUID, name: str) -> uuid.UUID:
    from radd.modules.itemtypes import service as itemtypes_service

    for issue_type in await itemtypes_service.list_types(session, project_id):
        if issue_type.name.lower() == name.lower():
            return issue_type.id
    raise NotFoundError("issue type", name)


async def _cycle_id(session: AsyncSession, name: str) -> uuid.UUID:
    from radd.modules.cycles import service as cycles_service

    for cycle in await cycles_service.list_cycles(session):
        if cycle.name.lower() == name.lower():
            return cycle.id
    raise NotFoundError("cycle", name)


async def _category_id(session: AsyncSession, name: str) -> uuid.UUID:
    from radd.modules.timelogging import categories as timelogging_categories

    for category in await timelogging_categories.list_categories(session):
        if category.name.lower() == name.lower():
            return category.id
    raise NotFoundError("work category", name)


def _item_summary(read: ItemRead) -> dict[str, Any]:
    return {
        "key": read.key,
        "kind": read.kind.value,
        "title": read.title,
        "state": read.state.name,
        "priority": read.priority.value,
        "assignee": read.assignee.name if read.assignee else None,
        "labels": read.labels,
        "updated_at": read.updated_at.isoformat(),
    }


def _item_write_fields(args: Mapping[str, Any]) -> dict[str, Any]:
    """Write values shared by create/update that need no DB resolution."""
    values: dict[str, Any] = {}
    if args.get("title") is not None:
        values["title"] = str(args["title"])
    if args.get("description") is not None:
        values["description"] = str(args["description"])
    if args.get("priority") is not None:
        values["priority"] = Priority(args["priority"])
    if args.get("labels") is not None:
        values["labels"] = [str(label) for label in args["labels"]]
    if args.get("custom_fields") is not None:
        values["custom_fields"] = dict(args["custom_fields"])
    return values


# --- tracker tool handlers ---


async def _search_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    slq = str(args["slq"]).strip()
    reads = await items_service.list_items(
        session, actor=actor, filters=ItemListFilters(), q=slq or None, limit=_limit(args), offset=0
    )
    return {"items": [_item_summary(read) for read in reads], "count": len(reads)}


async def _find_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Hybrid text search (spec 103): routes through search.service.search, so
    every MCP client inherits FTS+vector fusion — and any future ranking
    upgrade — with no client-side change."""
    from radd.modules.search import service as search_service

    hits = await search_service.search(
        session, actor, str(args["query"]), limit=_limit(args)
    )
    return {
        "items": [
            {
                "key": hit.key,
                "title": hit.title,
                "snippet": hit.snippet,
            }
            for hit in hits
        ],
        "count": len(hits),
    }


async def _link_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Link two items by KEY (RADD-739).

    Keys, not ids or per-project numbers: every other tool in the catalog
    addresses items by key, and an agent that just created two items holds their
    keys and nothing else. Enforcement is `items_service.add_item_link`'s own —
    it requires `item.update` on the SOURCE item's project and validates the type
    against the spec-91 catalog, so nothing is re-derived here.
    """
    source = await items_service.get_item_by_key(session, str(args["from_key"]), actor=actor)
    target = await items_service.get_item_by_key(session, str(args["to_key"]), actor=actor)
    read = await items_service.add_item_link(
        session,
        source.id,
        ItemLinkCreate(target_id=target.id, link_type=str(args["type"])),
        actor=actor,
    )
    return {
        "key": read.key,
        "links": {
            "outgoing": [
                {"type": link.link_type, "key": link.item.key, "title": link.item.title}
                for link in read.links.outgoing
            ],
            "incoming": [
                {"type": link.link_type, "key": link.item.key, "title": link.item.title}
                for link in read.links.incoming
            ],
        },
    }


async def _unlink_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Remove a link, addressed the way it was created rather than by link id —
    an agent that made a link does not keep its uuid, and asking it to list the
    item first to find one would make removal a two-call dance."""
    source = await items_service.get_item_by_key(session, str(args["from_key"]), actor=actor)
    target = await items_service.get_item_by_key(session, str(args["to_key"]), actor=actor)
    link_type = str(args["type"])
    match = next(
        (
            link
            for link in source.links.outgoing
            if link.item.key == target.key and link.link_type == link_type
        ),
        None,
    )
    if match is None:
        raise NotFoundError(
            ItemEntity.LINK, f"{source.key} -{link_type}-> {target.key}"
        )
    await items_service.remove_item_link(session, source.id, match.id, actor=actor)
    return {"removed": {"from": source.key, "to": target.key, "type": link_type}}


async def _get_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    comments = await comments_service.list_comments(session, read.id, actor=actor)
    tail = comments[-GET_ITEM_COMMENTS_TAIL:]
    return {
        "item": read.model_dump(mode="json"),
        "comments": [comment.model_dump(mode="json") for comment in tail],
        "comment_total": len(comments),
    }


async def _resolve_relational_writes(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    args: Mapping[str, Any],
    values: dict[str, Any],
) -> None:
    """type/parent/cycle/estimate shared by create+update (RADD-673). Present-and-
    null clears, like assignee_email — pydantic's model_fields_set carries the
    distinction through to the service."""
    if args.get("type") is not None:
        values["type_id"] = await _type_id(session, project_id, str(args["type"]))
    if "parent" in args:
        parent_key = args["parent"]
        values["parent_id"] = (
            (await items_service.get_item_by_key(session, str(parent_key), actor=actor)).id
            if parent_key
            else None
        )
    if "cycle" in args:
        cycle_name = args["cycle"]
        values["cycle_id"] = await _cycle_id(session, str(cycle_name)) if cycle_name else None
    if "estimate_points" in args:
        raw_points = args["estimate_points"]
        values["estimate_points"] = float(raw_points) if raw_points is not None else None


async def _create_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await _project_by_key(session, str(args["project_key"]))
    values = _item_write_fields(args)
    values["project_id"] = project.id
    values["title"] = str(args["title"])
    if args.get("kind") is not None:
        values["kind"] = ItemKind(args["kind"])
    if args.get("state") is not None:
        values["state_id"] = await _state_id(session, project.id, str(args["state"]))
    if args.get("assignee_email"):
        values["assignee_id"] = await _user_id_by_email(session, str(args["assignee_email"]))
    await _resolve_relational_writes(session, actor, project.id, args, values)
    read = await items_service.create_item(session, ItemCreate(**values), actor=actor)
    return read.model_dump(mode="json")


async def _update_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    values = _item_write_fields(args)
    if args.get("state") is not None:
        values["state_id"] = await _state_id(session, current.project_id, str(args["state"]))
    if "assignee_email" in args:  # present-and-null clears the assignee
        email = args["assignee_email"]
        values["assignee_id"] = await _user_id_by_email(session, str(email)) if email else None
    await _resolve_relational_writes(session, actor, current.project_id, args, values)
    read = await items_service.update_item(session, current.id, ItemUpdate(**values), actor=actor)
    return read.model_dump(mode="json")


async def _comment_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    visibility = CommentVisibility.INTERNAL if args.get("internal") else CommentVisibility.PUBLIC
    comment = await comments_service.create_comment(
        session,
        current.id,
        CommentCreate(body=str(args["body"]), visibility=visibility),
        actor=actor,
    )
    return comment.model_dump(mode="json")


async def _list_projects(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
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


# --- doc tool handlers (feature-detected, see pages_bridge) ---


async def _get_page(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    functions = pages_bridge.pages_functions()
    if functions is None:
        raise UnknownToolError(McpTool.GET_PAGE)
    page_id = uuid.UUID(str(args["id"]))
    result = await pages_bridge.call_pages(functions[0], session, actor, page_id=page_id, id=page_id)
    return pages_bridge.jsonable(result)


async def _search_docs(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    functions = pages_bridge.pages_functions()
    if functions is None:
        raise UnknownToolError(McpTool.SEARCH_PAGES)
    query = str(args["query"])
    limit = _limit(args)
    # Spec 86: docs are global — a single search over every space.
    result = await pages_bridge.call_pages(
        functions[1],
        session,
        actor,
        q=query,
        query=query,
        text=query,
        limit=limit,
    )
    jsonable = pages_bridge.jsonable(result)
    results = jsonable if isinstance(jsonable, list) else [jsonable]
    return results[:limit]


# --- dispatch ---


# --- spec 114 families ---------------------------------------------------


async def _get_allowed_transitions(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    item = await items_service.require_item(session, read.id)
    project = await projects_service.get_project(session, read.project_id)
    allowed = await workflow_transitions.allowed_transitions(session, project, item)
    return allowed.model_dump(mode="json") if hasattr(allowed, "model_dump") else allowed


async def _transition_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """A guard refusal is a DOMAIN error carrying the reason, which the router
    turns into an isError result with that text — the agent learns why."""
    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    state_id = await _state_id(session, current.project_id, str(args["state"]))
    read = await items_service.update_item(
        session, current.id, ItemUpdate(state_id=state_id), actor=actor
    )
    return read.model_dump(mode="json")


async def _log_work(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    from datetime import date as _date

    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    worked_on = _date.fromisoformat(str(args["worked_on"])) if args.get("worked_on") else None
    category_id = (
        await _category_id(session, str(args["category"])) if args.get("category") else None
    )
    entry = await timelogging_service.create_worklog(
        session,
        read.id,
        WorklogCreate(
            time_spent=str(args["time_spent"]),
            worked_on=worked_on,
            category_id=category_id,
            note=str(args.get("note") or ""),
        ),
        author_id=actor.id,
        today=_date.today(),
    )
    return entry.model_dump(mode="json")


async def _update_worklog(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Correct a time entry (RADD-741).

    The gap this closes was found by hitting it: an allocation came out two
    minutes over the session's wall clock, and trimming it had to go to REST
    because MCP could log time but never correct it. Logged time is the one thing
    the working agreement insists must be derived rather than estimated, which
    makes "I got it slightly wrong" a routine event, not an edge case.

    Row-level authorization is `timelogging.service.authorize_mutation` — the
    same function the REST router calls, so an agent can do exactly what a person
    can and nothing more. The catalog atom is only the floor.
    """
    from datetime import date as _date

    worklog = await timelogging_service.get_worklog(session, uuid.UUID(str(args["worklog_id"])))
    await timelogging_service.authorize_mutation(
        session, actor, worklog, others=Permission.PROJECT_MANAGE
    )
    values: dict[str, Any] = {}
    if args.get("time_spent"):
        values["time_spent"] = str(args["time_spent"])
    if args.get("worked_on"):
        values["worked_on"] = _date.fromisoformat(str(args["worked_on"]))
    if args.get("note") is not None:
        values["note"] = str(args["note"])
    if args.get("category"):
        values["category_id"] = await _category_id(session, str(args["category"]))
    read = await timelogging_service.update_worklog(
        session, worklog, WorklogUpdate(**values), actor.id
    )
    return read.model_dump(mode="json")


async def _delete_worklog(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Destroying logged time is not a correction, so it takes the stricter atom
    when the entry is someone else's — the same split spec 50 already makes."""
    worklog = await timelogging_service.get_worklog(session, uuid.UUID(str(args["worklog_id"])))
    await timelogging_service.authorize_mutation(
        session, actor, worklog, others=Permission.WORKLOG_DELETE
    )
    await timelogging_service.delete_worklog(session, worklog, actor.id)
    return {"deleted": str(worklog.id)}


async def _list_worklogs(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """The timesheet, reachable by an agent. Scope rules are the router's: without
    `timesheet.view` you see your own time and nobody else's, and the SLQ can only
    narrow that — it is ANDed onto the scope filters inside build()."""
    from datetime import date as _date, timedelta as _timedelta

    # RADD-672: item.read anywhere admits the caller; the broad-view check stays
    # GLOBAL — timesheet.view is instance-wide, and a scoped key without it
    # defaults to its own time, which the SLQ below can only narrow.
    await authz.require_anywhere(session, actor, Permission.ITEM_READ, refuse_when_empty=True)
    global_permissions = await authz.effective_permissions(session, actor)
    user_ids = None if Permission.TIMESHEET_VIEW in global_permissions else {actor.id}
    end = _date.fromisoformat(str(args["end"])) if args.get("end") else _date.today()
    start = (
        _date.fromisoformat(str(args["start"]))
        if args.get("start")
        else end - _timedelta(days=WORKLOG_WINDOW_DAYS)
    )
    where = None
    if args.get("slq") and str(args["slq"]).strip():
        hours_per_day = await timelogging_service._hours_per_day(session)
        where = (
            await compile_worklog_query(
                session,
                worklog_parse(str(args["slq"])),
                current_user_id=actor.id,
                hours_per_day=hours_per_day,
            )
        ).where
    sheet = await timesheet.build(session, start, end, actor=actor, user_ids=user_ids, where=where)
    entries = [entry.model_dump(mode="json") for entry in sheet.entries[: _limit(args)]]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_seconds": sheet.total_seconds,
        "entries": entries,
    }


async def _list_releases(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await _project_by_key(session, str(args["project_key"]))
    await authz.require(session, actor, Permission.ITEM_READ, project=project)
    releases = await releases_service.list_releases(session, project.id)
    return [
        {"id": str(r.id), "version": r.version, "name": r.name, "status": r.status}
        for r in releases
    ]


async def _create_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await _project_by_key(session, str(args["project_key"]))
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
    from radd.modules.releases import pipeline as releases_pipeline

    project = await _project_by_key(session, str(args["project_key"]))
    await authz.require(session, actor, Permission.RELEASE_UPDATE, project=project)
    version = str(args["version"])
    releases = await releases_service.list_releases(session, project.id)
    release = next((r for r in releases if r.version == version), None)
    if release is None:
        raise NotFoundError("release", version)
    moved = await releases_pipeline.sweep(session, project, release)
    return {"release": release.version, "items_shipped": moved}


async def _set_item_release(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
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
    return read.model_dump(mode="json")


async def _list_users(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    await authz.require(session, actor, Permission.USER_MANAGE)
    users = await auth_service.list_users(session, q=args.get("q") or None)
    return [
        {"id": str(u.id), "email": u.email, "name": u.name, "active": u.active,
         "instance_role": u.instance_role, "source": u.source}
        for u in users[: _limit(args)]
    ]


async def _list_service_accounts(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    await authz.require(session, actor, Permission.GLOBAL_MANAGE)
    accounts = await service_accounts.list_accounts(session)
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "email": a.email,
            "active": a.active,
            "keys": await service_accounts.token_count(session, a.id),
        }
        for a in accounts
    ]


async def _create_service_account(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    await authz.require(session, actor, Permission.SERVICE_ACCOUNT_CREATE)
    account = await service_accounts.create_account(
        session,
        ServiceAccountCreate(
            name=str(args["name"]), description=str(args.get("description") or "")
        ),
        actor_id=actor.id,
    )
    return {"id": str(account.id), "name": account.name, "email": account.email}


_HANDLERS: dict[McpTool, Callable[..., Any]] = {
    McpTool.SEARCH_ITEMS: _search_items,
    McpTool.FIND_ITEMS: _find_items,
    McpTool.GET_ITEM: _get_item,
    McpTool.CREATE_ITEM: _create_item,
    McpTool.UPDATE_ITEM: _update_item,
    McpTool.COMMENT_ITEM: _comment_item,
    McpTool.LINK_ITEMS: _link_items,
    McpTool.UNLINK_ITEMS: _unlink_items,
    McpTool.LIST_PROJECTS: _list_projects,
    McpTool.GET_PAGE: _get_page,
    McpTool.SEARCH_PAGES: _search_docs,
    McpTool.GET_ALLOWED_TRANSITIONS: _get_allowed_transitions,
    McpTool.TRANSITION_ITEM: _transition_item,
    McpTool.LOG_WORK: _log_work,
    McpTool.LIST_WORKLOGS: _list_worklogs,
    McpTool.UPDATE_WORKLOG: _update_worklog,
    McpTool.DELETE_WORKLOG: _delete_worklog,
    McpTool.LIST_RELEASES: _list_releases,
    McpTool.CREATE_RELEASE: _create_release,
    McpTool.SWEEP_RELEASE: _sweep_release,
    McpTool.SET_ITEM_RELEASE: _set_item_release,
    McpTool.LIST_USERS: _list_users,
    McpTool.LIST_SERVICE_ACCOUNTS: _list_service_accounts,
    McpTool.CREATE_SERVICE_ACCOUNT: _create_service_account,
}


async def _call_registry_tool(
    session: AsyncSession, actor: User, spec: Any, arguments: Mapping[str, Any]
) -> Any:
    """A plugin tool inherits ENFORCEMENT, not just catalog filtering (RADD-640):
    the kernel requires the declared atom before the handler runs, so a plugin
    cannot accidentally expose an unfiltered tool. When the spec names a project
    parameter and the call carries it, the atom is required on THAT project."""
    project = None
    if spec.project_param and arguments.get(spec.project_param):
        project = await _project_by_key(session, str(arguments[spec.project_param]))
    if spec.permission:
        await authz.require(session, actor, cast(Permission, spec.permission), project=project)
    return await spec.handler(session, actor, arguments)


async def call_tool(
    session: AsyncSession, actor: User, name: str, arguments: Mapping[str, Any]
) -> Any:
    """Dispatch one tools/call: builtins first, then kernel-registered plugin
    tools (RADD-640 — a live lookup, so a disabled plugin's tools stop
    dispatching the moment they leave the catalog). Raises UnknownToolError for
    names in neither; RaddError subclasses bubble up for the router to shape
    into `isError: true` results."""
    try:
        tool = McpTool(name)
    except ValueError:
        from radd.kernel import registries  # deferred: keep the kernel import lazy

        spec = registries.mcp_tools.get(name)
        if spec is None:
            raise UnknownToolError(name) from None
        return await _call_registry_tool(session, actor, spec, arguments)
    if tool in PAGE_TOOLS and not pages_bridge.pages_available():
        raise UnknownToolError(name)
    return await _HANDLERS[tool](session, actor, arguments)
