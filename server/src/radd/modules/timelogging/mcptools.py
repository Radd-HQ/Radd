"""The worklog MCP tools (spec 114 / RADD-741), declared by their owner
(RADD-889).

Handlers moved verbatim from mcp/tools.py. Row-level authorization is
`authorize_mutation` — the same function the REST router calls — and the
listing's scope rules are the timesheet's own, so `kernel_enforced=False`: the
spec's `permission` is the spec-114 catalog FLOOR, not the enforcement.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.kernel.mcptools import limit_arg, limit_property, object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import categories as timelogging_categories, service as timelogging_service, timesheet
from .schemas import WorklogCreate, WorklogUpdate
from .slq import compile_worklog_query, parse as worklog_parse

WORKLOG_WINDOW_DAYS = 30  # spec 114: list_worklogs default window


async def _category_id(session: AsyncSession, name: str) -> uuid.UUID:
    for category in await timelogging_categories.list_categories(session):
        if category.name.lower() == name.lower():
            return category.id
    raise NotFoundError("work category", name)


async def _log_work(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    from datetime import date as _date

    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    project = await projects_service.get_project(session, read.project_id)
    await authz.require(session, actor, Permission.WORKLOG_WRITE, project=project)
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
    return {
        "id": str(entry.id),
        "time_spent": entry.time_spent,
        "worked_on": entry.worked_on.isoformat(),
    }


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
    return {
        "id": str(read.id),
        "time_spent": read.time_spent,
        "worked_on": read.worked_on.isoformat(),
    }


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
                denied_item_fields=await items_service.denied_slq_fields(session, actor, None),
            )
        ).where
    sheet = await timesheet.build(session, start, end, actor=actor, user_ids=user_ids, where=where)
    entries = [entry.model_dump(mode="json") for entry in sheet.entries[: limit_arg(args)]]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_seconds": sheet.total_seconds,
        "entries": entries,
    }


def _worklog_id_property(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


LOG_WORK = McpToolSpec(
    name="log_work",
    description="Log time against an item.",
    input_schema=object_schema(
        {
            "key": {"type": "string", "description": "Item key, e.g. TD-42."},
            "time_spent": {"type": "string", "description": "Jira-style, e.g. '2h 30m'."},
            "worked_on": {"type": "string", "description": "ISO date; defaults to today."},
            "category": {
                "type": "string",
                "description": "Work category NAME, e.g. Development (RADD-673).",
            },
            "note": {"type": "string"},
        },
        ["key", "time_spent"],
    ),
    handler=_log_work,
    permission=Permission.WORKLOG_WRITE,
    project_scoped=True,
    kernel_enforced=False,
)

# RADD-741: worklog.write is the CATALOG floor — anyone who may log time may
# correct their own entry. Editing someone else's still needs project.manage
# and deleting still needs worklog.delete, enforced per row by
# `timelogging.service.authorize_mutation`, which the REST router also uses.
UPDATE_WORKLOG = McpToolSpec(
    name="update_worklog",
    description="Correct a time entry — the amount, the date, the note or the "
    "category. Find the id with list_worklogs. Editing someone else's entry needs "
    "project.manage; deleting is a separate tool.",
    input_schema=object_schema(
        {
            "worklog_id": _worklog_id_property("The entry's id, as returned by list_worklogs."),
            "time_spent": {"type": "string", "description": "Jira-style, e.g. '2h 30m'."},
            "worked_on": {"type": "string", "description": "ISO date."},
            "category": {"type": "string", "description": "Work category NAME."},
            "note": {"type": "string"},
        },
        ["worklog_id"],
    ),
    handler=_update_worklog,
    permission=Permission.WORKLOG_WRITE,
    project_scoped=True,
    kernel_enforced=False,
)

DELETE_WORKLOG = McpToolSpec(
    name="delete_worklog",
    description="Delete a time entry. Its own tool rather than an update flag, "
    "because destroying logged time is not a correction — it needs worklog.delete "
    "when the entry is someone else's.",
    input_schema=object_schema(
        {"worklog_id": _worklog_id_property("The entry's id.")},
        ["worklog_id"],
    ),
    handler=_delete_worklog,
    permission=Permission.WORKLOG_WRITE,
    project_scoped=True,
    kernel_enforced=False,
)

LIST_WORKLOGS = McpToolSpec(
    name="list_worklogs",
    description="Time entries, filtered with the WORKLOG SLQ dialect "
    "(author, category, worked_on, time, note, and issue.<field> delegated to items).",
    input_schema=object_schema(
        {
            "slq": {"type": "string"},
            "start": {"type": "string", "description": "ISO date; defaults to 30 days back."},
            "end": {"type": "string", "description": "ISO date; defaults to today."},
            "limit": limit_property(),
        },
        [],
    ),
    handler=_list_worklogs,
    permission=Permission.WORKLOG_WRITE,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (LOG_WORK, UPDATE_WORKLOG, DELETE_WORKLOG, LIST_WORKLOGS)
