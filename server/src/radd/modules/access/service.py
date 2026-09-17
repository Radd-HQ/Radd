"""Access-grant CRUD + batch loading (spec 92).

The single service every resource's grants flow through — validates the subject
(user/team/role exist), the access (against the resource's ResourceSpec), and the
scope (project exists; global allowed), then stores/loads/clears rows. Resolution
lives in `resolution.py`; this is persistence + validation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service

# `AccessGrant` is re-exported here as the PUBLIC grant row type (RADD-887,
# the events.Event pattern from RADD-886): the row is what the resolution
# helpers and every share-shaped read return, and importing it from
# access.models made four modules reach into another module's models file.
# The ratchet test bans `access.models` outside this module.
from .models import AccessGrant, AccessRestriction
from .registry import get_spec
from .resolution import SubjectContext, effective_level
from .types import AccessEntity, AccessEvent, GrantEffect, GrantSubject
from radd.clock import utcnow

__all__ = ["AccessGrant"]  # re-exported public seam (see above)


# --- queries ------------------------------------------------------------------


def _live_clause():
    """RADD-820: expiry applies at RESOLUTION — filtered where grants LOAD, so
    the pure resolver never learns about clocks."""

    now = utcnow()
    return AccessGrant.expires_at.is_(None) | (AccessGrant.expires_at > now)


async def list_for_resource(
    session: AsyncSession, resource_type: str, resource_id: str, *,
    project_id: uuid.UUID | None = None, global_only: bool = False,
) -> list[AccessGrant]:
    query = select(AccessGrant).where(
        AccessGrant.resource_type == resource_type,
        AccessGrant.resource_id == resource_id,
        _live_clause(),
    )
    if project_id is not None:
        query = query.where(AccessGrant.project_id == project_id)
    elif global_only:
        query = query.where(AccessGrant.project_id.is_(None))
    result = await session.execute(query.order_by(AccessGrant.access, AccessGrant.subject_type))
    return list(result.scalars())


async def grants_for_resources(
    session: AsyncSession,
    resource_type: str,
    resource_ids: Iterable[str],
    *,
    include_expired: bool = False,
) -> dict[str, list[AccessGrant]]:
    """Batch: {resource_id: grants} — one query for a page of fields/views (no N+1).

    `include_expired=True` is for explicit history/diagnostic reads only.
    Authorization consumers must use the default liveness filter."""
    ids = [str(r) for r in resource_ids]
    out: dict[str, list[AccessGrant]] = {rid: [] for rid in ids}
    if not ids:
        return out
    conditions = [
        AccessGrant.resource_type == resource_type,
        AccessGrant.resource_id.in_(ids),
    ]
    if not include_expired:
        conditions.append(_live_clause())
    result = await session.execute(select(AccessGrant).where(*conditions))
    for grant in result.scalars():
        out.setdefault(grant.resource_id, []).append(grant)
    spec = get_spec(resource_type)
    if spec is not None and spec.default_open and not spec.hierarchical:
        policies = await session.scalars(select(AccessRestriction).where(
            AccessRestriction.resource_type == resource_type, AccessRestriction.resource_id.in_(ids)))
        for policy in policies:
            out.setdefault(policy.resource_id, []).append(_restriction_marker(policy))
    return out


def shared_resource_level(
    resource_type: str, grants: list[AccessGrant], *, user_id: uuid.UUID,
    team_ids: set[uuid.UUID], group_ids: set[uuid.UUID], global_access: str | None,
) -> str | None:
    """Shared hierarchical resource policy for view/dashboard consumers.

    Load live grants first. Public access is a fallback level, not a bypass
    around explicit denials; owners retain the owning module's intrinsic rights.
    """
    spec = get_spec(resource_type)
    if spec is None or not spec.hierarchical:
        return None
    context = SubjectContext(user_id=user_id, team_ids=frozenset(team_ids),
                             group_ids=frozenset(group_ids))
    return effective_level(grants, context, None, spec, default_level=global_access)


async def shared_resource_visible_clause(
    session: AsyncSession, actor, resource_type: str, *, resource_id, owner_id, global_access,
):
    """Public SQL seam: filter shared catalogs before count/limit/hydration."""
    from radd.modules.groups import service as groups
    from radd.modules.teams import service as teams
    from .shared import visible_clause

    spec = get_spec(resource_type)
    if spec is None:
        raise ValueError(f"unknown shared resource {resource_type}")
    context = SubjectContext(user_id=actor.id,
        team_ids=frozenset(await teams.user_team_ids(session, actor.id)),
        group_ids=frozenset(await groups.user_group_ids(session, actor.id)))
    return visible_clause(spec, context, resource_id=resource_id, owner_id=owner_id,
                          global_access=global_access, live=_live_clause())


async def shared_resource_state_expressions(session, actor, resource_type, *, resource_id,
                                             global_access):
    """Public SQL seam for bounded sharing flags and exact allow/deny levels."""
    from radd.modules.groups import service as groups
    from radd.modules.teams import service as teams
    from .shared import state_expressions

    spec = get_spec(resource_type)
    if spec is None:
        raise ValueError(f"unknown shared resource {resource_type}")
    context = SubjectContext(user_id=actor.id,
        team_ids=frozenset(await teams.user_team_ids(session, actor.id)),
        group_ids=frozenset(await groups.user_group_ids(session, actor.id)))
    return state_expressions(spec, context, resource_id=resource_id,
                             global_access=global_access, live=_live_clause())


async def count_resource_grants(session, resource_type, resource_id):
    """Count current grants without loading policy rows or subject objects."""
    from sqlalchemy import func

    return await session.scalar(select(func.count()).select_from(AccessGrant).where(
        AccessGrant.resource_type == resource_type, AccessGrant.resource_id == resource_id,
        _live_clause())) or 0


async def resource_ids_with_grants(
    session: AsyncSession, resource_type: str, *, ids: list[str] | None = None,
) -> set[str]:
    """Distinct resource ids carrying ANY grant row (expired included) — drives
    the fields module's `restricted` read flag (RADD-887)."""
    query = select(AccessGrant.resource_id).where(AccessGrant.resource_type == resource_type)
    if ids is not None:
        if not ids:
            return set()
        query = query.where(AccessGrant.resource_id.in_(ids))
    rows = await session.execute(query.distinct())
    policy_query = select(AccessRestriction.resource_id).where(AccessRestriction.resource_type == resource_type)
    if ids is not None:
        policy_query = policy_query.where(AccessRestriction.resource_id.in_(ids))
    return set(rows.scalars()) | set(await session.scalars(policy_query))


async def get_grant(session: AsyncSession, grant_id: uuid.UUID) -> AccessGrant:
    grant = await session.get(AccessGrant, grant_id)
    if grant is None:
        raise NotFoundError(AccessEntity.GRANT, grant_id)
    return grant


# --- mutation -----------------------------------------------------------------


async def lock_resource(session: AsyncSession, resource_type: str, resource_id: str) -> None:
    """Lock through the owning module before grant authorization or mutation."""
    from sqlalchemy import text

    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                          {"key": f"access:{resource_type}:{resource_id}"})
    spec = get_spec(resource_type)
    if spec is not None and spec.lock_resource is not None:
        await spec.lock_resource(session, resource_id)


async def apply_shared_grant_edits(session, resource_type, resource_id, data, *, actor_id):
    """Public write seam; the owner authorizes and owns the encompassing savepoint."""
    from .shared_writes import apply_edits

    await apply_edits(session, resource_type, resource_id, data, actor_id=actor_id)


async def _validate_subject(
    session: AsyncSession, subject_type: GrantSubject, subject_id: uuid.UUID
) -> None:
    from radd.modules.auth import roles as roles_service, service as users_service
    from radd.modules.groups import service as groups_service
    from radd.modules.teams import service as teams_service

    if subject_type is GrantSubject.USER:
        if subject_id not in await users_service.users_by_ids(session, [subject_id]):
            raise ConflictError(AccessEntity.GRANT, reason=f"no such user {subject_id}")
    elif subject_type is GrantSubject.TEAM:
        if (await teams_service.teams_by_ids(session, [subject_id])).get(subject_id) is None:
            raise ConflictError(AccessEntity.GRANT, reason=f"no such team {subject_id}")
    elif subject_type is GrantSubject.GROUP:
        if (await groups_service.groups_by_ids(session, [subject_id])).get(subject_id) is None:
            raise ConflictError(AccessEntity.GRANT, reason=f"no such group {subject_id}")
    else:  # ROLE
        if (await roles_service.roles_by_ids(session, {subject_id})).get(subject_id) is None:
            raise ConflictError(AccessEntity.GRANT, reason=f"no such role {subject_id}")


async def add_grant(
    session: AsyncSession,
    resource_type: str,
    resource_id: str,
    *,
    subject_type: GrantSubject,
    subject_id: uuid.UUID,
    access: str,
    project_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    effect: GrantEffect = GrantEffect.ALLOW,
    expires_at=None,
) -> AccessGrant:
    await lock_resource(session, resource_type, resource_id)
    spec = get_spec(resource_type)
    if spec is None:
        raise ConflictError(AccessEntity.GRANT, reason=f"unknown resource type '{resource_type}'")
    if subject_type not in spec.subjects:
        raise ConflictError(AccessEntity.GRANT, reason=f"{subject_type} not allowed here")
    if access not in spec.accesses:
        raise ConflictError(AccessEntity.GRANT, reason=f"unknown access '{access}'")
    if project_id is not None and not spec.project_scoped:
        raise ConflictError(AccessEntity.GRANT, reason=f"{resource_type} grants can't be scoped")
    await _validate_subject(session, subject_type, subject_id)
    if project_id is not None:
        await projects_service.get_project(session, project_id)
    # Guard duplicates (a NULL project_id isn't caught by the unique constraint).
    dup = await session.scalar(
        select(AccessGrant.id).where(
            AccessGrant.resource_type == resource_type,
            AccessGrant.resource_id == resource_id,
            AccessGrant.subject_type == subject_type.value,
            AccessGrant.subject_id == subject_id,
            AccessGrant.access == access,
            AccessGrant.project_id.is_(None)
            if project_id is None
            else AccessGrant.project_id == project_id,
        )
    )
    if dup is not None:
        raise ConflictError(AccessEntity.GRANT, reason="that grant already exists")
    grant = AccessGrant(
        resource_type=resource_type,
        resource_id=resource_id,
        subject_type=subject_type.value,
        subject_id=subject_id,
        access=access,
        project_id=project_id,
        effect=effect.value,
        expires_at=expires_at,
        granted_by=actor_id,
    )
    session.add(grant)
    if spec.default_open and not spec.hierarchical and effect == GrantEffect.ALLOW:
        from sqlalchemy.dialects.postgresql import insert
        await session.execute(insert(AccessRestriction).values(
            resource_type=resource_type, resource_id=resource_id, access=access, project_id=project_id
        ).on_conflict_do_nothing(constraint="uq_access_restriction_scope"))
    await session.flush()
    await _emit(session, AccessEvent.GRANTED, grant, actor_id)
    return grant


async def remove_grant(
    session: AsyncSession, grant_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> AccessGrant:
    grant = await get_grant(session, grant_id)
    await lock_resource(session, grant.resource_type, grant.resource_id)
    grant = await session.scalar(
        select(AccessGrant).where(AccessGrant.id == grant_id).execution_options(populate_existing=True)
    )
    if grant is None:
        raise NotFoundError(AccessEntity.GRANT, grant_id)
    await _emit(session, AccessEvent.REVOKED, grant, actor_id)
    await session.delete(grant)
    await session.flush()
    return grant


async def clear_resource(
    session: AsyncSession, resource_type: str, resource_id: str
) -> None:
    """Drop every grant on a resource — called when the resource itself is deleted
    (grants have no FK to their polymorphic resource)."""
    await session.execute(delete(AccessRestriction).where(
        AccessRestriction.resource_type == resource_type, AccessRestriction.resource_id == resource_id))
    await session.execute(
        delete(AccessGrant).where(
            AccessGrant.resource_type == resource_type, AccessGrant.resource_id == resource_id
        )
    )


async def remove_subject_grants(
    session: AsyncSession,
    resource_type: str,
    resource_id: str,
    *,
    subject_type: GrantSubject,
    subject_id: uuid.UUID,
) -> None:
    """Drop every grant ONE subject holds on one resource — the views/dashboards
    ownership transfer clears the new owner's now-redundant share rows this way
    (RADD-887). No REVOKED events, matching those callers: a transfer emits its
    own UPDATED event."""
    await session.execute(
        delete(AccessGrant).where(
            AccessGrant.resource_type == resource_type,
            AccessGrant.resource_id == resource_id,
            AccessGrant.subject_type == subject_type.value,
            AccessGrant.subject_id == subject_id,
        )
    )


async def clear_resource_types(
    session: AsyncSession, resource_types: Iterable[str]
) -> int:
    """Drop EVERY grant of the given resource types, returning how many rows went
    — pluginmgr's uninstall sweep (RADD-818) removes a departing plugin's grant
    types wholesale (RADD-887). No per-row events: the sweep emits one summary."""
    types = list(resource_types)
    if not types:
        return 0
    await session.execute(delete(AccessRestriction).where(AccessRestriction.resource_type.in_(types)))
    result = await session.execute(
        delete(AccessGrant).where(AccessGrant.resource_type.in_(types))
    )
    return result.rowcount or 0


async def _subject_label(session: AsyncSession, grant: AccessGrant) -> str:
    """The grant's subject as an auditor reads it (spec 123): a name, not an id."""
    from radd.modules.auth import roles as roles_service, service as users_service
    from radd.modules.teams import service as teams_service

    try:
        if grant.subject_type == GrantSubject.USER:
            user = (await users_service.users_by_ids(session, [grant.subject_id])).get(grant.subject_id)
            return user.name if user else str(grant.subject_id)
        if grant.subject_type == GrantSubject.TEAM:
            team = (await teams_service.teams_by_ids(session, [grant.subject_id])).get(grant.subject_id)
            return f"team {team.name}" if team else str(grant.subject_id)
        if grant.subject_type == GrantSubject.ROLE:
            return f"role {(await roles_service.get_role(session, grant.subject_id)).name}"
    except Exception:  # noqa: BLE001 — a label is decoration on an audit row, never a failed write
        pass
    return str(grant.subject_id)


async def _emit(
    session: AsyncSession, event: AccessEvent, grant: AccessGrant, actor_id: uuid.UUID | None, *, changes=None
) -> None:
    await events.emit(
        session,
        event_type=event,
        entity_type=AccessEntity.GRANT,
        entity_id=grant.id,
        changes=changes,
        actor_id=actor_id,
        subjects={"project": grant.project_id},
        payload={
            "resource_type": grant.resource_type,
            "resource_id": grant.resource_id,
            "subject_type": grant.subject_type,
            "subject": await _subject_label(session, grant),
            "subject_id": str(grant.subject_id),
            "access": grant.access,
            "effect": grant.effect,
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "project_id": str(grant.project_id) if grant.project_id else None,
        },
    )


async def sweep_expired_grants() -> int:
    """RADD-820: delete expired rows from BOTH grant tables. Resolution already
    treats them as absent (the liveness clauses) — this only stops the tables
    accumulating corpses. Registered on the kernel task registry."""

    from radd.db import SessionLocal
    from radd.modules.auth.models import GlobalRoleGrant

    now = utcnow()
    async with SessionLocal() as session:
        removed = 0
        for model in (AccessGrant, GlobalRoleGrant):
            result = await session.execute(
                delete(model).where(model.expires_at.is_not(None), model.expires_at <= now)
            )
            removed += result.rowcount or 0
        await session.commit()
    return removed


def _restriction_marker(policy):
    # Internal resolver input, never a persisted grant or a directory row. It
    # restricts the access without matching any principal.
    from types import SimpleNamespace
    return SimpleNamespace(id=policy.id, resource_id=policy.resource_id,
        resource_type=policy.resource_type, access=policy.access, project_id=policy.project_id,
        subject_type="restriction", subject_id=uuid.UUID(int=0), effect=GrantEffect.ALLOW.value,
        granted_by=None, expires_at=None)


async def restriction_modes(session, resource_type, resource_id):
    rows = await session.scalars(select(AccessRestriction).where(
        AccessRestriction.resource_type == resource_type, AccessRestriction.resource_id == resource_id))
    return [{"id": row.id, "access": row.access, "project_id": row.project_id} for row in rows]


async def restore_inheritance(session, policy_id, actor_id):
    policy = await session.get(AccessRestriction, policy_id)
    if policy is None:
        raise NotFoundError(AccessEntity.GRANT, policy_id)
    # Remove remaining allows for this access/scope; keep explicit denies.
    await session.execute(delete(AccessGrant).where(
        AccessGrant.resource_type == policy.resource_type, AccessGrant.resource_id == policy.resource_id,
        AccessGrant.access == policy.access, AccessGrant.project_id == policy.project_id,
        AccessGrant.effect == GrantEffect.ALLOW))
    await _emit(session, AccessEvent.REVOKED, _restriction_marker(policy), actor_id)
    await session.delete(policy)
    await session.flush()
