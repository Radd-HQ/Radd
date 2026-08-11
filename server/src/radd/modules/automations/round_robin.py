"""Round-robin team assignment for the `assign_round_robin` action (RADD-1044).

Triage distributes: nothing here picks a FIXED person (that is `set_assignee`) —
it walks a team's members in a stable order and hands the next ticket to the next
eligible member, skipping inactive accounts and anyone currently AWAY.

Three decisions live in this file, and each is load-bearing:

* **Stable ordering by user id.** `list_team_members` sorts by NAME, which renames
  and reorders; the rotation is walked by user id (a total order that never shifts
  as members join, leave, or are renamed) so the stored cursor stays meaningful.
  Fairness is identical to join-order — every member is reached once per lap —
  and the id comparison is what lets "the next member after the cursor" be a plain
  `id > last` even when the cursor-holder has since left the team.
* **The cursor advances to the ASSIGNEE, never to a skipped member.** Away and
  inactive members are passed over on the way to the next eligible one; the cursor
  lands on whoever the ticket went to. A run with no eligible member leaves the
  cursor where it was — nothing was assigned, so there is nothing to advance past.
* **Leave is optional.** The away check is a DEFERRED, feature-detected import,
  exactly like `email_action.py`'s reach for mailintake's `contact` role: the
  `leave` module may be unloaded, and then away-skipping is simply off (inactive
  accounts are still skipped) rather than a crash.
"""

import uuid
from datetime import date
from types import ModuleType

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.teams import service as teams_service
from radd.modules.teams.models import Team

from .models import TeamAssignmentCursor

LEAVE_MODULE = "radd.modules.leave"


def leave_service() -> ModuleType | None:
    """leave's public seam, or None when the module is not loaded.

    Feature-detection mirrors `email_action.mailintake_service`: an optional,
    disableable module reached DEFERRED, so an instance without it does not import
    it and away-skipping degrades to off rather than erroring."""
    if LEAVE_MODULE not in settings.modules:
        return None
    from radd.modules.leave import service as leave_svc

    return leave_svc


async def _away_user_ids(session: AsyncSession) -> set[uuid.UUID]:
    """The users away TODAY, or the empty set when leave is unloaded."""
    leave = leave_service()
    if leave is None:
        return set()
    return {entry.user_id for entry in await leave.current(session, date.today())}


async def pick_next(session: AsyncSession, team: Team) -> uuid.UUID | None:
    """The next member of `team` to assign to, or None when none is eligible.

    Read-only: the caller advances the cursor at APPLY time (so a dry run picks
    without moving the rotation). Members are ordered by user id; the next pick is
    the first eligible member whose id sorts strictly after the stored cursor,
    wrapping to the first when the cursor is unset or names the last of the lap.
    """
    members = await teams_service.list_team_members(session, team.id)
    away = await _away_user_ids(session)
    eligible = sorted(
        (user for user in members if user.active and user.id not in away),
        key=lambda user: user.id,
    )
    if not eligible:
        return None

    last = await session.scalar(
        select(TeamAssignmentCursor.last_assigned_user_id).where(
            TeamAssignmentCursor.team_id == team.id
        )
    )
    if last is not None:
        # First eligible member after the cursor. This is robust to the
        # cursor-holder having left the team or gone away since — they are simply
        # not in `eligible`, and the walk resumes at whoever comes after where
        # they would have been.
        for user in eligible:
            if user.id > last:
                return user.id
    return eligible[0].id


async def advance_cursor(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Point the team's cursor at `user_id` — the member just assigned.

    An upsert, so the first assignment for a team creates the row. Executed as a
    Core statement (not read back through `pick_next`'s scalar select) so the next
    item's pick in the same transaction sees the new value: reading the entity
    through the identity map would return a stale in-session copy instead.
    """
    await session.execute(
        pg_insert(TeamAssignmentCursor)
        .values(team_id=team_id, last_assigned_user_id=user_id)
        .on_conflict_do_update(
            index_elements=[TeamAssignmentCursor.team_id],
            set_={"last_assigned_user_id": user_id},
        )
    )
