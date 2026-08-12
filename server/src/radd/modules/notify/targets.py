"""Which subscription targets an actor may NAME (spec 118).

A subscription's `scope_id` is a uuid the client chooses, and two things follow
from that if nobody checks it.

**A name oracle.** Delivery is safe on its own — every notification still passes
`consumer._allowed` or `pages.refs.readable_page_ids_for_users`, so a rule
pointing at a project you cannot read delivers nothing. But the preferences READ
resolves each target's name for display, because a settings page that renders
"Subscribed to 3f2a-…" is a page nobody can audit. Store an arbitrary uuid, read
it back, and that display is a lookup service for the name and key of every
project, space and team on the instance. On this product that is frequently the
name of an unannounced customer.

**And a rule set with no gate is a row per uuid somebody cares to send** — the
`max_length` on the request bounds the count, this bounds what they can point at.

The gate is per family, and it is the same one the PICKER that offers the target
uses, so the API and the UI cannot disagree about what exists:

* project — `authz.visible_projects`, exactly `GET /projects` (RADD-937/1041);
* team — `team.read`, exactly `GET /teams`, which is all-or-nothing (RADD-816);
* space — `pages.access.readable_spaces`, exactly `GET /page-spaces` (RADD-791).

It is applied on BOTH sides. The write drops a target the actor may not name; the
read refuses to label one. Two applications rather than one because a stored row
outlives the access that created it — someone removed from a project keeps the
subscription row until their next save, and until then the read must not narrate
it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User

from .types import SUBSCRIPTION_SCOPES, RuleScope

#: What `readable_targets` answers with: {subscription scope: allowed target ids}.
ReadableTargets = dict[RuleScope, set[uuid.UUID]]


def targets_by_scope(
    rows: Iterable[tuple[RuleScope, uuid.UUID | None]],
) -> dict[RuleScope, set[uuid.UUID]]:
    """Group the subscription targets a rule set names, by family.

    Relationship rows are dropped here rather than checked and passed: they have
    no target, so there is nothing to be entitled to.
    """
    wanted: dict[RuleScope, set[uuid.UUID]] = {}
    for scope, scope_id in rows:
        if scope_id is not None and scope in SUBSCRIPTION_SCOPES:
            wanted.setdefault(scope, set()).add(scope_id)
    return wanted


def _pages_access():
    """The wiki's space-read seam, or None when the plugin is not loaded.

    The module's usual deferred feature-detected import: `pages` loads AFTER
    notify and is disableable. Absent, no space target is readable — which is the
    correct answer, not a degradation: an instance with no wiki has no spaces.
    """
    try:
        from radd.modules.pages import access as pages_access
    except ImportError:
        return None
    return pages_access


async def readable_targets(
    session: AsyncSession, user: User, wanted: Mapping[RuleScope, set[uuid.UUID]]
) -> ReadableTargets:
    """Of the targets asked about, the ones this actor may name.

    Nothing is resolved for a family nobody asked about — a matrix-only save
    costs no extra query at all, which is what keeps this on the write path
    rather than in a background sweep.
    """
    readable: ReadableTargets = {}

    projects = wanted.get(RuleScope.PROJECT) or set()
    if projects:
        visible = await authz.visible_projects(session, user)
        readable[RuleScope.PROJECT] = projects & set(visible)

    teams = wanted.get(RuleScope.TEAM) or set()
    if teams:
        # `GET /teams` gates the whole CATALOG on one atom and then serves every
        # team, so the catalog gate is the target gate. Asking a narrower
        # question per team would invent an entitlement the surface offering
        # those teams does not have.
        allowed = await authz.holds(session, user, Permission.TEAM_READ)
        readable[RuleScope.TEAM] = set(teams) if allowed else set()

    spaces = wanted.get(RuleScope.SPACE) or set()
    if spaces:
        pages_access = _pages_access()
        if pages_access is None:
            readable[RuleScope.SPACE] = set()
        else:
            visible_spaces = await pages_access.readable_spaces(session, user)
            readable[RuleScope.SPACE] = spaces & set(visible_spaces)

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
