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
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.projects.models import Project
from radd.modules.teams import service as teams

from . import rules as rules_policy, service
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
    return {
        scope: {
            kind: channel
            for kind, channel in rules_policy.DEFAULT_MATRIX[scope].items()
        }
        for scope in RELATIONSHIP_SCOPES
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
    """
    if not ids:
        return {}
    try:
        from radd.modules.pages import service as pages_service
    except ImportError:
        return {}
    spaces = await pages_service.list_spaces(session)
    return {space.id: space.name for space in spaces if space.id in ids}


async def _labels(
    session: AsyncSession, rows: list[NotificationRule]
) -> dict[uuid.UUID, str]:
    by_scope: dict[str, set[uuid.UUID]] = {}
    for row in rows:
        if row.scope_id is not None:
            by_scope.setdefault(row.scope, set()).add(row.scope_id)
    labels: dict[uuid.UUID, str] = {}
    labels |= await _project_names(session, by_scope.get(RuleScope.PROJECT.value, set()))
    labels |= await _team_names(session, by_scope.get(RuleScope.TEAM.value, set()))
    labels |= await _space_names(session, by_scope.get(RuleScope.SPACE.value, set()))
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


async def read(session: AsyncSession, user_id: uuid.UUID) -> NotificationPrefsRead:
    rows = await service.list_rules(session, user_id)
    labels = await _labels(session, rows)
    prefs = await service.get_prefs(session, user_id)
    reads = [read for read in (_rule_read(row, labels) for row in rows) if read is not None]
    return NotificationPrefsRead(
        kinds=_kind_reads(),
        scopes=list(RELATIONSHIP_SCOPES),
        defaults=_defaults(),
        rules=reads,
        email_digest=True if prefs is None else prefs.email_digest,
    )
