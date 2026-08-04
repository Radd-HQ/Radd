"""Pure access resolution (spec 92) — no DB, fully unit-testable.

Given a resource's grants + the actor's subject context + the current project,
decide read/write (flag model) or the effective level (hierarchical model). This
is the ONE place access is decided; every consumer resolves through it, so a
custom field, a builtin field, a view, and a plugin resource all behave alike.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .registry import ResourceSpec
from .types import GrantSubject


class _GrantLike(Protocol):
    subject_type: str
    subject_id: uuid.UUID
    access: str
    project_id: uuid.UUID | None


@dataclass(frozen=True, kw_only=True)
class SubjectContext:
    """What the acting user brings to a grant check, in one scope. `role_ids` are the
    roles the user holds ON THIS PROJECT (direct + team + project-scoped grants), so
    a role-subject grant is inherently project-aware. `has_manage` bypasses (a
    project/resource manager always passes).

    `group_ids` (RADD-830) is REQUIRED on purpose — no default. The user's
    transitive directory groups are part of the subject graph, and a
    construction site that forgets them must fail to COMPILE, because at
    runtime it fails as a quiet access denial the day RADD-832 makes groups
    grant subjects. Pass `frozenset()` explicitly where groups genuinely
    don't apply (pure unit fixtures)."""

    group_ids: frozenset[uuid.UUID]
    user_id: uuid.UUID | None = None
    role_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    team_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    has_manage: bool = False


def in_scope(grant: _GrantLike, project_id: uuid.UUID | None) -> bool:
    """A grant applies here when it's global (no project) or matches the project."""
    return grant.project_id is None or grant.project_id == project_id


def subject_matches(grant: _GrantLike, ctx: SubjectContext) -> bool:
    if grant.subject_type == GrantSubject.USER.value:
        return ctx.user_id is not None and grant.subject_id == ctx.user_id
    if grant.subject_type == GrantSubject.TEAM.value:
        return grant.subject_id in ctx.team_ids
    if grant.subject_type == GrantSubject.ROLE.value:
        return grant.subject_id in ctx.role_ids
    return False


def has_access(
    grants: Sequence[_GrantLike],
    ctx: SubjectContext,
    access: str,
    project_id: uuid.UUID | None,
    spec: ResourceSpec,
) -> bool:
    """Flag model (fields): an access is OPEN until some in-scope grant restricts it;
    once restricted, the actor needs a matching grant of that access (or one that
    implies it — write implies read), or `has_manage`."""
    restricting = [g for g in grants if g.access == access and in_scope(g, project_id)]
    if not restricting:
        return spec.default_open
    if ctx.has_manage:
        return True
    satisfying = (access, *spec.implied_by.get(access, ()))
    return any(
        subject_matches(g, ctx)
        for g in grants
        if g.access in satisfying and in_scope(g, project_id)
    )


def effective_level(
    grants: Sequence[_GrantLike],
    ctx: SubjectContext,
    project_id: uuid.UUID | None,
    spec: ResourceSpec,
) -> str | None:
    """Hierarchical model (views): the HIGHEST access level the actor holds via an
    in-scope matching grant, by the order of `spec.accesses` (last = highest). None
    = no access (closed-default resources are invisible)."""
    order = {a: i for i, a in enumerate(spec.accesses)}
    held = [
        g.access
        for g in grants
        if in_scope(g, project_id) and g.access in order and subject_matches(g, ctx)
    ]
    if not held:
        return None
    return max(held, key=lambda a: order[a])


def restricted_accesses(
    grants: Sequence[_GrantLike], access: str, project_id: uuid.UUID | None
) -> bool:
    """Whether ANY in-scope grant restricts `access` (drives x-restricted flags)."""
    return any(g.access == access and in_scope(g, project_id) for g in grants)
