"""Round-robin team assignment for `assign_round_robin` (RADD-1044).

* Members are walked in USER-ID order (not name): a total order that survives
  renames and leavers, so "next after the cursor" is simply `id > last`.
* The cursor advances to the ASSIGNEE only; skipped (inactive/away) members
  never move it, and a run with nobody eligible leaves it alone.
* Away comes from the PERSON_AVAILABILITY socket (union of providers); with
  none registered nobody is away. Never imported from `leave`.
"""

import logging
import uuid
from collections.abc import Collection
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets
from radd.modules.teams import service as teams_service
from radd.modules.teams.models import Team

from .models import TeamAssignmentCursor

logger = logging.getLogger(__name__)


async def away_user_ids(
    session: AsyncSession, day: date, user_ids: Collection[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of `user_ids` are away on `day` — the UNION over every live
    PERSON_AVAILABILITY provider, or nobody when none is registered.

    A provider that raises is logged and skipped rather than failing the
    assignment: a broken calendar degrades toward "nobody is away", which is
    what an instance without leave does anyway — the ticket still gets an owner.
    """
    if not user_ids:
        return set()
    away: set[uuid.UUID] = set()
    for name, provider in sockets.providers(sockets.Socket.PERSON_AVAILABILITY).items():
        try:
            away.update(await provider.away_user_ids(session, day, user_ids))
        except Exception:  # noqa: BLE001 — one bad calendar must not stop triage
            logger.exception("round robin: availability provider %r failed — ignored", name)
    return away


async def pick_next(session: AsyncSession, team: Team) -> uuid.UUID | None:
    """The next member of `team` to assign to, or None when none is eligible.

    Read-only: the caller advances the cursor at APPLY time (so a dry run picks
    without moving the rotation). Members are ordered by user id; the next pick is
    the first eligible member whose id sorts strictly after the stored cursor,
    wrapping to the first when the cursor is unset or names the last of the lap.
    """
    members = [user for user in await teams_service.list_team_members(session, team.id) if user.active]
    away = await away_user_ids(session, date.today(), [user.id for user in members])
    eligible = sorted(
        (user for user in members if user.id not in away),
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
