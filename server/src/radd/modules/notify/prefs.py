"""Assembling the preferences payload (spec 118).

Out of the router because it is not routing: it joins three registries (the kind
vocabulary, the scope defaults, the saved rules) and resolves each
subscription's TARGET NAME, which is a query per entity family and a deferred
import for the one that loads later.

**A subscription is shown by name or not at all.** A rule row stores a uuid; a
settings page that renders "Subscribed to 3f2a-…" is a page nobody can audit.
The label is resolved at READ, not stored at write, for the reason every other
display value in this module is: a project renamed after the subscription was
saved should read as its new name, not as the one it had that afternoon.

**And only for a target this actor may read.** That name resolution is the one
place a rule row's uuid becomes prose, which makes it the whole of the exposure
the write gate closes from the other side — see `targets.py`. A row whose target
is not readable comes back label-less and the page shows it as unavailable, which
is also the honest rendering for a target that has been deleted: from here the
two are the same fact.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.projects.models import Project
from radd.modules.teams import service as teams

from . import rules as rules_policy, service, targets
from .kinds import NOTIFICATION_KINDS
from .models import NotificationRule
from .schemas import (
    NotificationKindRead,
    NotificationPrefsRead,
    NotificationRuleRead,
)
from .types import RELATIONSHIP_SCOPES, Channel, NotificationType, RuleScope


def _kind_reads() -> list[NotificationKindRead]:
    return [
        NotificationKindRead(
            kind=spec.kind,
            label=spec.label,
            description=spec.description,
            personal=spec.personal,
        )
        for spec in NOTIFICATION_KINDS
    ]


def _defaults() -> dict[RuleScope, dict[NotificationType, Channel]]:
    """What an unset cell resolves to, for EVERY scope — not just the columns.

    A subscription's unset cell needs one too, and it is not the `own` column's
    value: a subscriber with no other relation to the project has exactly one
    applicable scope, so the resolver falls to `DEFAULT_MATRIX[project]`, which is
    `off`. The SPA showed the `own` value there and named "Mine" as the source,
    which described a delivery that does not happen — the one thing a settings
    page must not do. Serving every scope's defaults is what keeps the fix from
    becoming a hardcoded `off` on the client, one more copy of this table to
    drift.

    `scopes` stays the three relationship columns: this is the inheritance
    lookup, not the list of columns to render.
    """
    return {
        scope: dict(rules_policy.DEFAULT_MATRIX[scope]) for scope in RuleScope
    }


async def _project_names(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Project.id, Project.key, Project.name).where(Project.id.in_(ids))
    )
    # "KEY · Name" the way pinned view tabs disambiguate: two projects called
    # "Platform" are common, two with the same key are impossible.
    return {row_id: f"{key} · {name}" for row_id, key, name in rows.all()}


async def _team_names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    found = await teams.teams_by_ids(session, ids)
    return {team_id: team.name for team_id, team in found.items()}


async def _space_names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Space names, or nothing when the wiki plugin is not loaded.

    The deferred feature-detected import this module uses everywhere for pages:
    it loads AFTER notify and is disableable, so a space subscription on an
    instance with the wiki turned off degrades to an unlabelled row rather than
    an ImportError in a settings page.

    `ids` is already narrowed to what the actor may read — the caller does that
    (`targets.readable_targets`), so listing every space here names none of them.
    """
    if not ids:
        return {}
    try:
        from radd.modules.pages import service as pages_service
    except ImportError:
        return {}
    spaces = await pages_service.list_spaces(session)
    return {space.id: space.name for space in spaces if space.id in ids}


def _scope_of(row: NotificationRule) -> RuleScope | None:
    try:
        return RuleScope(row.scope)
    except ValueError:
        return None


async def _labels(
    session: AsyncSession, user: User, rows: list[NotificationRule]
) -> dict[uuid.UUID, str]:
    """Target names, for the targets this actor may read and no others.

    The narrowing happens BEFORE the name queries rather than after, so an
    unreadable target is never fetched — which is the difference between a filter
    and a gate when the thing being filtered is the answer itself.
    """
    readable = await targets.readable_targets(
        session,
        user,
        targets.targets_by_scope(
            (scope, row.scope_id) for row in rows if (scope := _scope_of(row)) is not None
        ),
    )
    labels: dict[uuid.UUID, str] = {}
    labels |= await _project_names(session, readable.get(RuleScope.PROJECT, set()))
    labels |= await _team_names(session, readable.get(RuleScope.TEAM, set()))
    labels |= await _space_names(session, readable.get(RuleScope.SPACE, set()))
    return labels


def _rule_read(row: NotificationRule, labels: dict[uuid.UUID, str]) -> NotificationRuleRead | None:
    try:
        scope = RuleScope(row.scope)
    except ValueError:
        return None
    channels: dict[NotificationType, Channel] = {}
    for kind, channel in (row.channels or {}).items():
        try:
            channels[NotificationType(kind)] = Channel(channel)
        except ValueError:
            continue  # normalised out on the next save; not worth failing a read
    return NotificationRuleRead(
        scope=scope,
        scope_id=row.scope_id,
        scope_label=labels.get(row.scope_id) if row.scope_id is not None else None,
        channels=channels,
    )


async def read(session: AsyncSession, user: User) -> NotificationPrefsRead:
    rows = await service.list_rules(session, user.id)
    labels = await _labels(session, user, rows)
    prefs = await service.get_prefs(session, user.id)
    reads = [read for read in (_rule_read(row, labels) for row in rows) if read is not None]
    return NotificationPrefsRead(
        kinds=_kind_reads(),
        scopes=list(RELATIONSHIP_SCOPES),
        defaults=_defaults(),
        rules=reads,
        email_digest=True if prefs is None else prefs.email_digest,
    )
