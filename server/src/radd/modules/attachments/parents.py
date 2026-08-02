"""Parent bindings (spec 102): what may own attachments, and who may touch them.

A binding maps an `entity_type` to the permission checks and context of its
owner. attachments registers the `item` binding itself (below); other modules
register theirs at their own plugin init — `docs` registers `page` — so
attachments never learns those modules exist (dev rule 1).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from .types import AttachmentEntity, AttachmentParentType

Guard = Callable[[AsyncSession, User, uuid.UUID], Awaitable[None]]
ProjectOf = Callable[[AsyncSession, uuid.UUID], Awaitable[uuid.UUID | None]]


@dataclass(frozen=True)
class ParentBinding:
    entity_type: str
    require_read: Guard  # view/list/download this parent's attachments
    require_write: Guard  # upload + delete-own
    require_admin: Guard  # delete anyone's
    project_id_of: ProjectOf  # feeds routing context + ACL SubjectContext; None = global


_BINDINGS: dict[str, ParentBinding] = {}


def register_parent(binding: ParentBinding) -> None:
    _BINDINGS[binding.entity_type] = binding


def binding_for(entity_type: str) -> ParentBinding:
    binding = _BINDINGS.get(entity_type)
    if binding is None:
        raise NotFoundError(AttachmentEntity.ATTACHMENT, f"parent type {entity_type!r}")
    return binding


# --- the item binding (attachments' own) --------------------------------------


async def _item_guard(
    session: AsyncSession, user: User, item_id: uuid.UUID, permission: Permission
) -> None:
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, permission, project=project)


async def _item_read(session: AsyncSession, user: User, item_id: uuid.UUID) -> None:
    await _item_guard(session, user, item_id, Permission.ITEM_READ)


async def _item_write(session: AsyncSession, user: User, item_id: uuid.UUID) -> None:
    await _item_guard(session, user, item_id, Permission.ITEM_UPDATE)


async def _item_admin(session: AsyncSession, user: User, item_id: uuid.UUID) -> None:
    await _item_guard(session, user, item_id, Permission.PROJECT_MANAGE)


async def _item_project_id(session: AsyncSession, item_id: uuid.UUID) -> uuid.UUID | None:
    item = await items_service.require_item(session, item_id)
    return item.project_id


register_parent(
    ParentBinding(
        entity_type=AttachmentParentType.ITEM.value,
        require_read=_item_read,
        require_write=_item_write,
        require_admin=_item_admin,
        project_id_of=_item_project_id,
    )
)
