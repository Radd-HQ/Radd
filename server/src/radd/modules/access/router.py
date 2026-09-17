"""The generic grants API (spec 92).

One set of endpoints for EVERY registered resource. Authorization is delegated to
the resource's `can_manage` hook (a field manager manages field grants, a view
owner manages view shares, …) so the router itself stays resource-agnostic — new
resources/plugins need no new endpoints.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from . import service, directory
from .registry import all_specs, get_spec
from .schemas import AccessGrantCreate, AccessGrantRead, AccessGrantDirectoryRead, ResourceSpecRead
from .types import AccessEntity, AccessEvent
from .schemas import AccessGrantExpiry

router = APIRouter(prefix="/grants", tags=["access"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require_manage(
    session: AsyncSession,
    actor: User,
    resource_type: str,
    resource_id: str,
    project_id: uuid.UUID | None = None,
):
    spec = get_spec(resource_type)
    if spec is None:
        raise ConflictError(AccessEntity.GRANT, reason=f"unknown resource type '{resource_type}'")
    if not await spec.can_manage(session, actor, resource_id, project_id):
        raise ForbiddenError(f"no permission to manage {resource_type} grants")
    return spec


async def _require_read_scope(session, user, resource_type, resource_id, project_id, global_only):
    if project_id is not None and global_only:
        raise HTTPException(
            status_code=422, detail="Choose a project or global-only scope, not both"
        )
    spec = await _require_manage(session, user, resource_type, resource_id, project_id)
    if project_id is not None and not spec.project_scoped:
        raise HTTPException(status_code=422, detail="This resource does not support project scope")


@router.get("/resources", response_model=list[ResourceSpecRead])
async def list_resource_specs(user: CurrentUser) -> list[ResourceSpecRead]:
    """Every registered resource's grant MODEL — which accesses exist, which
    subject kinds apply, whether grants can be project-scoped (RADD-947).

    `ResourceSpecRead` was written for this route and the route was never added,
    so `AccessGrantsEditor` grew its own answer instead: it took `accesses` and
    `subjectKinds` as props from each call site and rendered the project
    ScopePicker unconditionally — including for `page`, whose spec sets
    `project_scoped=False` and whose write path answers "page grants can't be
    scoped". A UI that offers what the validator rejects is a second opinion
    about one rule, and this is the same registry the validator reads.

    No `can_manage` check: this is the SHAPE of the access model, not anyone's
    grants, and the editor needs it before it can render the form that would be
    authorized. Any signed-in caller may read it.

    Declared before `/{grant_id}` — Starlette matches in declaration order, so a
    literal segment written after a UUID pattern is unreachable (RADD-761).
    """
    del user  # authentication is the gate; the catalog itself is not sensitive
    return [
        ResourceSpecRead(
            resource_type=spec.resource_type,
            label=spec.label or spec.resource_type,
            accesses=list(spec.accesses),
            subjects=list(spec.subjects),
            project_scoped=spec.project_scoped,
            hierarchical=spec.hierarchical,
            default_open=spec.default_open,
        )
        for spec in sorted(all_specs(), key=lambda s: s.label or s.resource_type)
    ]


@router.get("/directory", response_model=list[AccessGrantDirectoryRead])
async def grants_directory(
    resource_type: str,
    resource_id: str,
    session: Session,
    user: CurrentUser,
    response: Response,
    project_id: uuid.UUID | None = None,
    global_only: bool = False,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AccessGrantDirectoryRead]:
    await _require_read_scope(session, user, resource_type, resource_id, project_id, global_only)
    rows, total = await directory.page(
        session,
        user,
        resource_type,
        resource_id,
        q=q,
        limit=limit,
        offset=offset,
        project_id=project_id,
        global_only=global_only,
    )
    response.headers["X-Total-Count"] = str(total)
    return rows


@router.get("", response_model=list[AccessGrantRead])
async def list_grants(
    resource_type: str,
    resource_id: str,
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
    global_only: bool = False,
) -> list[AccessGrantRead]:
    await _require_read_scope(session, user, resource_type, resource_id, project_id, global_only)
    return [
        AccessGrantRead.model_validate(g)
        for g in await service.list_for_resource(
            session, resource_type, resource_id, project_id=project_id, global_only=global_only
        )
    ]


@router.post("", response_model=list[AccessGrantRead], status_code=201)
async def create_grant(
    data: AccessGrantCreate, session: Session, user: CurrentUser
) -> list[AccessGrantRead]:
    scopes: list[uuid.UUID | None] = list(dict.fromkeys(data.project_ids)) or [None]
    await service.lock_resource(session, data.resource_type, data.resource_id)
    for project_id in scopes:
        await _require_manage(session, user, data.resource_type, data.resource_id, project_id)
    rows = [
        await service.add_grant(
            session,
            data.resource_type,
            data.resource_id,
            subject_type=data.subject_type,
            subject_id=data.subject_id,
            access=data.access,
            project_id=project_id,
            actor_id=user.id,
            effect=data.effect,
            expires_at=data.expires_at.replace(tzinfo=None) if data.expires_at else None,
        )
        for project_id in scopes
    ]
    return [AccessGrantRead.model_validate(g) for g in rows]


@router.delete("/{grant_id}", status_code=204)
async def delete_grant(grant_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    grant = await service.get_grant(session, grant_id)
    await service.lock_resource(session, grant.resource_type, grant.resource_id)
    await _require_manage(session, user, grant.resource_type, grant.resource_id, grant.project_id)
    await service.remove_grant(session, grant_id, actor_id=user.id)


@router.get("/restrictions/{resource_type}/{resource_id}")
async def restriction_modes(resource_type: str, resource_id: str, session: Session, user: CurrentUser,
                            project_id: uuid.UUID | None = None, global_only: bool = False):
    await _require_read_scope(session, user, resource_type, resource_id, project_id, global_only)
    rows = await service.restriction_modes(session, resource_type, resource_id)
    if project_id is not None or global_only:
        rows = [row for row in rows if row["project_id"] == project_id]
    return rows


@router.delete("/restrictions/{policy_id}", status_code=204)
async def restore_inheritance(policy_id: uuid.UUID, session: Session, user: CurrentUser):
    from .models import AccessRestriction
    policy = await session.get(AccessRestriction, policy_id)
    if policy is None:
        from radd.exceptions import NotFoundError
        raise NotFoundError("restriction", policy_id)
    await service.lock_resource(session, policy.resource_type, policy.resource_id)
    await _require_manage(session, user, policy.resource_type, policy.resource_id, policy.project_id)
    await service.restore_inheritance(session, policy_id, user.id)


@router.patch("/{grant_id}", response_model=AccessGrantRead)
async def change_expiry(grant_id: uuid.UUID, data: AccessGrantExpiry, session: Session, user: CurrentUser):
    grant = await service.get_grant(session, grant_id)
    await service.lock_resource(session, grant.resource_type, grant.resource_id)
    await _require_manage(session, user, grant.resource_type, grant.resource_id, grant.project_id)
    previous_expiry = grant.expires_at
    grant.expires_at = data.expires_at.replace(tzinfo=None) if data.expires_at else None
    await session.flush()
    await service._emit(session, AccessEvent.GRANTED, grant, user.id, changes=[{"field": "expires_at", "from": previous_expiry.isoformat() if previous_expiry else None, "to": grant.expires_at.isoformat() if grant.expires_at else None}])
    return AccessGrantRead.model_validate(grant)
