"""Assembling the preferences payload (spec 118): kind vocabulary, per-scope
defaults, saved rules, and each subscription's target NAME — resolved at read
time and only for targets the actor may read (`targets.py`); an unreadable or
deleted target comes back label-less."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.projects.models import Project
from radd.modules.teams import service as teams

from . import rules as rules_policy, service, subjects, targets
from .kinds import all_specs
from .models import NotificationRule
from .schemas import (
    NotificationKindRead,
    NotificationPrefsRead,
    NotificationRuleRead,
)
from .types import RELATIONSHIP_SCOPES, Channel, RuleScope


def _kind_reads() -> list[NotificationKindRead]:
    return [
        NotificationKindRead(
            kind=spec.key,
            label=spec.label,
            description=spec.description,
            personal=spec.personal,
        )
        for spec in all_specs()
    ]


def _defaults() -> dict[RuleScope, dict[str, Channel]]:
    """Defaults for EVERY scope, not just the three columns: a subscription's
    unset cell resolves to its own scope's default (`off`), not `own`'s, and
    serving it keeps the client from hardcoding that."""
    matrix = rules_policy.default_matrix()
    return {
        scope: dict(matrix[scope]) for scope in RuleScope
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


async def _labels(
    session: AsyncSession, user: User, rows: list[NotificationRule]
) -> dict[uuid.UUID, str]:
    """Names for readable targets only — narrowed BEFORE the name queries."""
    wanted = targets.targets_by_scope(
        (scope, row.scope_id) for row in rows if (scope := service.scope_of(row)) is not None
    )
    core = {scope: ids for scope, ids in wanted.items() if scope in targets.CORE_TARGETS}
    readable = await targets.readable_targets(session, user, core)
    labels: dict[uuid.UUID, str] = {}
    labels |= await _project_names(session, readable.get(RuleScope.PROJECT, set()))
    labels |= await _team_names(session, readable.get(RuleScope.TEAM, set()))
    for scope, ids in wanted.items():
        if scope not in core:
            # A subject provider narrows and names in ONE call — the name is the
            # whole of what the gate protects (RADD-1385). No provider: unlabelled.
            labels |= await subjects.scope_names(session, user, scope, ids)
    return labels


def _rule_read(row: NotificationRule, labels: dict[uuid.UUID, str]) -> NotificationRuleRead | None:
    scope = service.scope_of(row)
    if scope is None:
        return None
    return NotificationRuleRead(
        scope=scope,
        scope_id=row.scope_id,
        scope_label=labels.get(row.scope_id) if row.scope_id is not None else None,
        # Unknown pairs are dropped, not failed on: the next save normalises them.
        channels=service.clean_channels(row.channels or {}),
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
