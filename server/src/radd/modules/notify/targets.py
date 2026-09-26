"""Which subscription targets an actor may NAME (spec 118).

`scope_id` is client-chosen and the preferences READ turns it into a name, so
an unchecked uuid is a name oracle for every project, space and team. The gate
per family is the one its picker uses: project → `authz.visible_projects`;
team → `team.read` (all-or-nothing, like `GET /teams`); space → the
`NOTIFICATION_SUBJECT` provider. Applied on BOTH sides — the write drops what
the actor may not name, the read refuses to label it — because a stored row
outlives the access that created it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User

from . import subjects
from .types import SUBSCRIPTION_SCOPES, RuleScope

#: What `readable_targets` answers with: {subscription scope: allowed target ids}.
ReadableTargets = dict[RuleScope, set[uuid.UUID]]

#: The subscription families notify gates itself. Any other names the container
#: of a non-item subject, and that subject's provider answers for it.
CORE_TARGETS: frozenset[RuleScope] = frozenset({RuleScope.PROJECT, RuleScope.TEAM})


def targets_by_scope(
    rows: Iterable[tuple[RuleScope, uuid.UUID | None]],
) -> dict[RuleScope, set[uuid.UUID]]:
    """The subscription targets a rule set names, by family (relationship rows name none)."""
    wanted: dict[RuleScope, set[uuid.UUID]] = {}
    for scope, scope_id in rows:
        if scope_id is not None and scope in SUBSCRIPTION_SCOPES:
            wanted.setdefault(scope, set()).add(scope_id)
    return wanted


async def readable_targets(
    session: AsyncSession, user: User, wanted: Mapping[RuleScope, set[uuid.UUID]]
) -> ReadableTargets:
    """Of the targets asked about, the ones this actor may name; a family nobody
    asked about costs no query."""
    readable: ReadableTargets = {}

    projects = wanted.get(RuleScope.PROJECT) or set()
    if projects:
        visible = await authz.visible_projects(session, user)
        readable[RuleScope.PROJECT] = projects & set(visible)

    teams = wanted.get(RuleScope.TEAM) or set()
    if teams:
        # `GET /teams` gates the whole catalog on one atom, so that is the target gate.
        allowed = await authz.holds(session, user, Permission.TEAM_READ)
        readable[RuleScope.TEAM] = set(teams) if allowed else set()

    for scope, ids in wanted.items():
        if scope in CORE_TARGETS or not ids:
            continue
        # A non-item subject's container (a wiki space): its provider answers;
        # no provider names none.
        readable[scope] = set(await subjects.scope_names(session, user, scope, set(ids)))

    return readable


def permitted(
    readable: Mapping[RuleScope, set[uuid.UUID]],
    scope: RuleScope,
    scope_id: uuid.UUID | None,
) -> bool:
    """May this rule row exist? Relationship rows always may — they name nobody."""
    if scope_id is None or scope not in SUBSCRIPTION_SCOPES:
        return True
    return scope_id in readable.get(scope, set())
