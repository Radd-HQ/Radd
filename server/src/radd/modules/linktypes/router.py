"""Issue link type admin (spec 91).

Reading the catalog is open to any authenticated user (the issue link picker needs
it); creating/editing/deleting types is instance-admin, like other instance-wide
schema config.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole

from . import service
from .models import LinkTypeDef
from .schemas import LinkTypeCreate, LinkTypeRead, LinkTypeUpdate

router = APIRouter(prefix="/link-types", tags=["link types"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_admin(actor: User) -> None:
    if InstanceRole(actor.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError("managing link types requires an instance admin")


def _to_read(definition: LinkTypeDef, usages: dict[str, int]) -> LinkTypeRead:
    read = LinkTypeRead.model_validate(definition)
    read.usages = usages.get(definition.key, 0)
    return read


@router.get("", response_model=list[LinkTypeRead])
async def list_link_types(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
) -> list[LinkTypeRead]:
    """Every link type (admin), or — with `project_id` — the manual types offered on
    an item in that project (global + project-scoped, auto-managed excluded)."""
    usages = await service.usage_counts(session)
    if project_id is not None:
        types = await service.types_for_project(session, project_id)
    else:
        types = await service.list_types(session)
    return [_to_read(t, usages) for t in types]


@router.post("", response_model=LinkTypeRead, status_code=201)
async def create_link_type(
    data: LinkTypeCreate, session: Session, user: CurrentUser
) -> LinkTypeRead:
    _require_admin(user)
    definition = await service.create_type(session, data, actor_id=user.id)
    return _to_read(definition, await service.usage_counts(session))


@router.patch("/{type_id}", response_model=LinkTypeRead)
async def update_link_type(
    type_id: uuid.UUID, data: LinkTypeUpdate, session: Session, user: CurrentUser
) -> LinkTypeRead:
    _require_admin(user)
    definition = await service.update_type(session, type_id, data, actor_id=user.id)
    return _to_read(definition, await service.usage_counts(session))


@router.delete("/{type_id}", status_code=204)
async def delete_link_type(type_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    _require_admin(user)
    await service.delete_type(session, type_id, actor_id=user.id)
