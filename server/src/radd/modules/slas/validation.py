"""RADD-1299 — a policy's "met when" choices and reporter-team filter must
name things that exist: states of THIS project, teams that exist, and a list
wherever the mode needs one. Refused on write (409), so evaluation never has
to guess what a half-configured target means."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.teams import service as teams
from radd.modules.workflow import service as workflow

from .models import SlaPolicy
from .types import STATE_MODES, SlaEntity, SlaKind, SlaMetOn

_DEFAULTS = {SlaKind.RESPONSE: SlaMetOn.FIRST_REPLY, SlaKind.RESOLUTION: SlaMetOn.DONE}


async def validate_rules(session: AsyncSession, policy: SlaPolicy) -> None:
    project_states = {str(state.id) for state in await workflow.list_states(session, policy.project_id)}
    wanted_teams: set[uuid.UUID] = {uuid.UUID(str(t)) for t in policy.reporter_team_ids or []}
    for kind in SlaKind:
        mode = SlaMetOn(getattr(policy, f"{kind.value}_met_on") or _DEFAULTS[kind])
        state_ids = [str(s) for s in getattr(policy, f"{kind.value}_state_ids") or []]
        team_ids = [str(t) for t in getattr(policy, f"{kind.value}_team_ids") or []]
        label = kind.value
        if mode in STATE_MODES:
            if not state_ids:
                raise ConflictError(SlaEntity.POLICY, reason=f"choose the states that complete the {label} target")
            if set(state_ids) - project_states:
                raise ConflictError(SlaEntity.POLICY, reason=f"the {label} target names a state outside this project")
        if mode is SlaMetOn.REPLY_BY_TEAMS:
            if not team_ids:
                raise ConflictError(SlaEntity.POLICY, reason=f"choose the teams whose reply completes the {label} target")
            wanted_teams |= {uuid.UUID(t) for t in team_ids}
    missing = wanted_teams - await teams.existing_ids(session, wanted_teams)
    if missing:
        raise ConflictError(SlaEntity.POLICY, reason="the policy names a team that does not exist")
