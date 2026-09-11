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
from typing import Protocol

from .registry import ResourceSpec
from .types import GrantEffect, GrantSubject


def _effect(grant: _GrantLike) -> str:
    # Rows predate the column in unit fixtures; absent = allow (the default).
    return getattr(grant, "effect", GrantEffect.ALLOW.value) or GrantEffect.ALLOW.value


def _deny_verdict(
    grants: Sequence["_GrantLike"],
    ctx: "SubjectContext",
    accesses: tuple[str, ...],
    project_id: uuid.UUID | None,
) -> bool | None:
    """RADD-819 precedence, decided once for both models. Returns True when a
    deny kills the access, None when denies decide nothing here.

    The rule, written down: SPECIFICITY FIRST, DENY ON TIES. A project-scoped
    row beats a global row regardless of effect (the narrower statement is the
    more deliberate one); at equal specificity a deny beats an allow. The one
    documented back door — the instance admin — lives at the resolvers'
    CALLERS, never here."""
    matching = [
        g
        for g in grants
        if g.access in accesses and in_scope(g, project_id) and subject_matches(g, ctx)
    ]
    denies = [g for g in matching if _effect(g) == GrantEffect.DENY.value]
    if not denies:
        return None
    allows = [g for g in matching if _effect(g) != GrantEffect.DENY.value]
    if any(g.project_id is not None for g in denies):
        return True  # a narrow deny: nothing narrower exists to carve it back
    # Only GLOBAL denies remain: a narrower (project-scoped) allow beats them.
    if any(g.project_id is not None for g in allows):
        return None
    return True


class _GrantLike(Protocol):
    subject_type: str
    subject_id: uuid.UUID
    access: str
    project_id: uuid.UUID | None
    effect: str  # "allow" | "deny" (RADD-819)


@dataclass(frozen=True, kw_only=True)
class SubjectContext:
    """What the acting user brings to a grant check, in one scope. `role_ids` are the
    roles the user holds ON THIS PROJECT (direct + team + project-scoped grants), so
    a role-subject grant is inherently project-aware. `has_manage` is a FACT
    the resolvers no longer consult (RADD-816/F5.2 removed the bypass) — kept
    on the context so call sites that own a deliberate resource-manage
    short-circuit can carry it, but it grants nothing here.

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
    if grant.subject_type == GrantSubject.GROUP.value:
        # ctx.group_ids is the TRANSITIVE closure (RADD-830), so a grant on a
        # parent group matches members of any nested descendant.
        return grant.subject_id in ctx.group_ids
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
    implies it — write implies read). RADD-816 (F5.2): `has_manage` no longer
    bypasses — a manager holds access the same way anyone does, through a
    matching grant, which is what lets the inspector EXPLAIN it. A resource
    that wants a manager bypass short-circuits at its own call site, where the
    decision is named and owned."""
    # RADD-819: denies resolve first — one deny row expresses "this team may
    # not", with nobody else's access touched (denies never RESTRICT a
    # default-open resource for non-matching subjects). A deny binds its EXACT
    # access; on an implied route (write satisfies read) it blocks THAT route
    # without closing the check sideways — deny write, and an open read stays
    # open, but write no longer answers for read.
    if _deny_verdict(grants, ctx, (access,), project_id):
        return False
    satisfying = tuple(
        a
        for a in (access, *spec.implied_by.get(access, ()))
        if not _deny_verdict(grants, ctx, (a,), project_id)
    )
    restricting = [
        g
        for g in grants
        if g.access == access
        and in_scope(g, project_id)
        and _effect(g) != GrantEffect.DENY.value
    ]
    if not restricting:
        return spec.default_open
    return any(
        subject_matches(g, ctx)
        for g in grants
        if g.access in satisfying
        and in_scope(g, project_id)
        and _effect(g) != GrantEffect.DENY.value
    )


def effective_level(
    grants: Sequence[_GrantLike],
    ctx: SubjectContext,
    project_id: uuid.UUID | None,
    spec: ResourceSpec,
    *,
    default_level: str | None = None,
) -> str | None:
    """Hierarchical model (views): the HIGHEST access level the actor holds via an
    in-scope matching grant, by the order of `spec.accesses` (last = highest). None
    = no access (closed-default resources are invisible). A public fallback
    level participates in the same exact-level deny policy as explicit grants;
    intrinsic ownership is a deliberate decision at the caller."""
    order = {a: i for i, a in enumerate(spec.accesses)}
    held = [
        g.access
        for g in grants
        if in_scope(g, project_id)
        and g.access in order
        and subject_matches(g, ctx)
        and _effect(g) != GrantEffect.DENY.value
        # RADD-819: a deny of a LEVEL removes that level from consideration.
        and not _deny_verdict(grants, ctx, (g.access,), project_id)
    ]
    if default_level in order and not _deny_verdict(grants, ctx, (default_level,), project_id):
        held.append(default_level)
    if not held:
        return None
    return max(held, key=lambda a: order[a])


def restricted_accesses(
    grants: Sequence[_GrantLike], access: str, project_id: uuid.UUID | None
) -> bool:
    """Whether ANY in-scope ALLOW grant restricts `access` (drives x-restricted
    flags). Denies don't restrict the world — they restrict their subject."""
    return any(
        g.access == access and in_scope(g, project_id) and _effect(g) != GrantEffect.DENY.value
        for g in grants
    )
