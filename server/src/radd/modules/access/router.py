"""The generic grants API (spec 92).

One set of endpoints for EVERY registered resource. Authorization is delegated to
the resource's `can_manage` hook (a field manager manages field grants, a view
owner manages view shares, …) so the router itself stays resource-agnostic — new
resources/plugins need no new endpoints.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from . import service
from .registry import all_specs, get_spec
from .schemas import AccessGrantCreate, AccessGrantRead, ResourceSpecRead
from .types import AccessEntity

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


@router.get("/resources", response_model=list[ResourceSpecRead])
async def list_resource_specs(user: CurrentUser) -> list[ResourceSpecRead]:
    """The registered resource types + their grant models — the GrantsEditor reads
    this to render access/subject choices for any resource (incl. plugins)."""
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
        for spec in all_specs()
    ]


@router.get("", response_model=list[AccessGrantRead])
async def list_grants(
    resource_type: str, resource_id: str, session: Session, user: CurrentUser
) -> list[AccessGrantRead]:
    await _require_manage(session, user, resource_type, resource_id)
    return [
        AccessGrantRead.model_validate(g)
        for g in await service.list_for_resource(session, resource_type, resource_id)
    ]


@router.post("", response_model=list[AccessGrantRead], status_code=201)
async def create_grant(
    data: AccessGrantCreate, session: Session, user: CurrentUser
) -> list[AccessGrantRead]:
    scopes: list[uuid.UUID | None] = list(dict.fromkeys(data.project_ids)) or [None]
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
        )
        for project_id in scopes
    ]
    return [AccessGrantRead.model_validate(g) for g in rows]


@router.delete("/{grant_id}", status_code=204)
async def delete_grant(grant_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    grant = await service.get_grant(session, grant_id)
    await _require_manage(session, user, grant.resource_type, grant.resource_id, grant.project_id)
    await service.remove_grant(session, grant_id, actor_id=user.id)
