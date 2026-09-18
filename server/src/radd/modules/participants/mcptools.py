"""Participants over MCP (RADD-1236, public report radd-hq/radd#8).

An agent asked to "add X as a participant" had two wrong answers — misuse
`assignee_email`, or hand the human back to the UI — because the roster was a
REST-only surface. These three tools address the item by KEY (every other tool
does) and the person by EMAIL or the team by NAME: the identity forms an agent
already holds from `list_users` and `update_item`, never a participant row id
it would first have to fetch.

Enforcement is the service's own (`item.update` OR being the item's reporter —
the identity path REST takes too), so `kernel_enforced=False`: a blanket
`item.update` gate here would refuse the reporter the feature exists for.
`item.update` remains the spec-114 catalog FLOOR.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.kernel.mcptools import object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import AuthEntity, Permission
from radd.modules.items import service as items_service
from radd.modules.teams import service as teams_service
from radd.modules.teams.types import TeamEntity

from . import service
from .schemas import ParticipantAdd, ParticipantRow

_SUBJECT_PROPERTIES: dict[str, Any] = {
    "key": {"type": "string", "description": "Item key, e.g. TD-42."},
    "email": {"type": "string", "description": "A person, by email (exactly one of email/team)."},
    "team": {"type": "string", "description": "A whole team, by name (exactly one of email/team)."},
}


async def _row(session: AsyncSession, row: ParticipantRow) -> dict[str, Any]:
    subject: dict[str, Any] = {"participant_id": str(row.id), "added_at": row.created_at.isoformat()}
    if row.user is not None:
        # The display ref carries no email, and the email is what an agent
        # addresses a person by — read it from the spine table.
        user = await session.get(User, row.user.id)
        subject.update(kind="user", name=row.user.name, email=user.email if user else None)
    elif row.team is not None:
        subject.update(kind="team", name=row.team.name)
    return subject


async def _subject(session: AsyncSession, args: Mapping[str, Any]) -> ParticipantAdd:
    email, team = args.get("email"), args.get("team")
    if (email is None) == (team is None):
        raise ValueError("exactly one of email/team is required")
    if email is not None:
        user = await auth_service.get_user_by_email(session, str(email))
        if user is None:
            raise NotFoundError(AuthEntity.USER, str(email))
        return ParticipantAdd(user_id=user.id)
    wanted = str(team).strip().lower()
    for candidate in await teams_service.list_teams(session, q=str(team)):
        if candidate.name.lower() == wanted:
            return ParticipantAdd(team_id=candidate.id)
    raise NotFoundError(TeamEntity.TEAM, str(team))


async def _list_participants(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    item = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    read = await service.list_participants(session, item.id, actor)
    return {
        "key": item.key,
        "can_manage": read.can_manage,
        "participants": [await _row(session, r) for r in read.rows],
    }


async def _add_participant(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    item = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    row = await service.add_participant(session, item.id, await _subject(session, args), actor)
    return {"key": item.key, "added": await _row(session, row)}


async def _remove_participant(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    item = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    wanted = await _subject(session, args)
    read = await service.list_participants(session, item.id, actor)
    match = next(
        (
            r for r in read.rows
            if (wanted.user_id is not None and r.user is not None and r.user.id == wanted.user_id)
            or (wanted.team_id is not None and r.team is not None and r.team.id == wanted.team_id)
        ),
        None,
    )
    if match is None:
        raise NotFoundError("participant", str(args.get("email") or args.get("team")))
    removed = await _row(session, match)
    await service.remove_participant(session, item.id, match.id, actor)
    return {"key": item.key, "removed": removed}


LIST_PARTICIPANTS = McpToolSpec(
    name="list_participants",
    description="Who follows an item: the people and teams added as participants "
    "(watchers), distinct from the assignee. `can_manage` says whether YOU may "
    "add or remove them (item.update, or being the item's reporter).",
    input_schema=object_schema({"key": _SUBJECT_PROPERTIES["key"]}, ["key"]),
    handler=_list_participants,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

ADD_PARTICIPANT = McpToolSpec(
    name="add_participant",
    description="Add a person (by email) or a whole team (by name) as a participant "
    "on an item, without touching the assignee. A person is auto-watched; a team "
    "follows with its CURRENT members. Already-present answers a conflict.",
    input_schema=object_schema(dict(_SUBJECT_PROPERTIES), ["key"]),
    handler=_add_participant,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

REMOVE_PARTICIPANT = McpToolSpec(
    name="remove_participant",
    description="Remove a participant — a person by email or a team by name — from "
    "an item. Removing yourself needs no permission at all.",
    input_schema=object_schema(dict(_SUBJECT_PROPERTIES), ["key"]),
    handler=_remove_participant,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (LIST_PARTICIPANTS, ADD_PARTICIPANT, REMOVE_PARTICIPANT)
