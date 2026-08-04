"""Provenance for the spec-92 half of the access system (RADD-809).

`permission_sources` explains atoms; this explains RESOURCE access — which
grant rows reach a subject, through what (the user directly, a named team, a
held role), at what scope, and what each resource type defaults to when no
grant restricts it ("readable because nothing restricts it" is a different
fact from "granted", and before this they looked identical from outside).

Same rule as RADD-779: a second pass over the same tables the resolver reads
(`resolution.py` stays the ONE place access is decided), off the request path
— it runs when an admin opens one person's row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AccessGrant
from .registry import all_specs
from .types import GrantSubject


@dataclass(frozen=True)
class ResourceAccessRow:
    """One grant row that reaches the inspected subject."""

    resource_type: str
    resource_id: str
    resource_label: str | None
    access: str
    effect: str  # allow | deny (RADD-819) — a deny row explains a refusal
    subject_type: str  # user | team | role | group — which subject kind matched
    subject_id: uuid.UUID
    subject_name: str | None  # team/role display name; None when it's the user directly
    project_id: uuid.UUID | None
    project_key: str | None  # scope display + backlink


@dataclass(frozen=True)
class ResourceTypeAccess:
    """Every matching grant for one registered resource type, plus the facts a
    reader needs to interpret an EMPTY list: open-by-default types are reachable
    with no rows at all."""

    resource_type: str
    label: str
    default_open: bool
    hierarchical: bool
    accesses: tuple[str, ...]
    rows: list[ResourceAccessRow]


async def subject_access(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    team_ids: Iterable[uuid.UUID] = (),
    role_ids: Iterable[uuid.UUID] = (),
    group_ids: Iterable[uuid.UUID] = (),
    team_names: Mapping[uuid.UUID, str] | None = None,
    role_names: Mapping[uuid.UUID, str] | None = None,
    group_names: Mapping[uuid.UUID, str] | None = None,
) -> list[ResourceTypeAccess]:
    """Every access grant reaching the given subjects, grouped per registered
    resource type. Registry-driven: a plugin's resource type appears with no
    edit here, exactly as its atoms already do. `group_ids` (RADD-832) is the
    caller's TRANSITIVE closure, so a grant on a parent group is reported."""
    team_ids = set(team_ids)
    role_ids = set(role_ids)
    group_ids = set(group_ids)
    conditions = []
    if user_id is not None:
        conditions.append(
            (AccessGrant.subject_type == GrantSubject.USER.value)
            & (AccessGrant.subject_id == user_id)
        )
    if team_ids:
        conditions.append(
            (AccessGrant.subject_type == GrantSubject.TEAM.value)
            & (AccessGrant.subject_id.in_(team_ids))
        )
    if role_ids:
        conditions.append(
            (AccessGrant.subject_type == GrantSubject.ROLE.value)
            & (AccessGrant.subject_id.in_(role_ids))
        )
    if group_ids:
        conditions.append(
            (AccessGrant.subject_type == GrantSubject.GROUP.value)
            & (AccessGrant.subject_id.in_(group_ids))
        )
    grants: list[AccessGrant] = []
    if conditions:
        result = await session.execute(
            select(AccessGrant)
            .where(or_(*conditions))
            .order_by(AccessGrant.resource_type, AccessGrant.resource_id, AccessGrant.access)
        )
        grants = list(result.scalars())

    project_keys = await _project_keys(session, {g.project_id for g in grants if g.project_id})
    by_type: dict[str, list[AccessGrant]] = {}
    for grant in grants:
        by_type.setdefault(grant.resource_type, []).append(grant)

    sections: list[ResourceTypeAccess] = []
    for spec in sorted(all_specs(), key=lambda s: s.label or s.resource_type):
        type_grants = by_type.get(spec.resource_type, [])
        labels: dict[str, str] = {}
        if type_grants and spec.label_for is not None:
            labels = await spec.label_for(session, sorted({g.resource_id for g in type_grants}))
        rows = [
            ResourceAccessRow(
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                resource_label=labels.get(grant.resource_id),
                access=grant.access,
                effect=grant.effect or "allow",
                subject_type=grant.subject_type,
                subject_id=grant.subject_id,
                subject_name=_subject_name(
                    grant, team_names or {}, role_names or {}, group_names or {}
                ),
                project_id=grant.project_id,
                project_key=project_keys.get(grant.project_id) if grant.project_id else None,
            )
            for grant in type_grants
        ]
        sections.append(
            ResourceTypeAccess(
                resource_type=spec.resource_type,
                label=spec.label or spec.resource_type,
                default_open=spec.default_open,
                hierarchical=spec.hierarchical,
                accesses=spec.accesses,
                rows=rows,
            )
        )
    return sections


def _subject_name(
    grant: AccessGrant,
    team_names: Mapping[uuid.UUID, str],
    role_names: Mapping[uuid.UUID, str],
    group_names: Mapping[uuid.UUID, str],
) -> str | None:
    if grant.subject_type == GrantSubject.TEAM.value:
        return team_names.get(grant.subject_id)
    if grant.subject_type == GrantSubject.ROLE.value:
        return role_names.get(grant.subject_id)
    if grant.subject_type == GrantSubject.GROUP.value:
        return group_names.get(grant.subject_id)
    return None


async def _project_keys(
    session: AsyncSession, project_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not project_ids:
        return {}
    from radd.modules.projects import service as projects_service

    return await projects_service.project_keys(session, project_ids)
