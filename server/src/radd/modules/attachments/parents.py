"""Parent bindings (spec 102): what may own attachments, and who may touch them.
attachments registers `item` itself; other modules register theirs (`pages`
registers `page`), so attachments never learns they exist."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.items.enums import ItemEvent
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.items import service as items_service

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
    #: The parent's deletion event — `gc` derives this parent's cleanup from it
    #: (RADD-744/745). Required: a default would silently leak bytes.
    deleted_event: str
    space_id_of: ProjectOf | None = None


_BINDINGS: dict[str, ParentBinding] = {}


def register_parent(binding: ParentBinding) -> None:
    """Register a parent; its cleanup follows, because the plugin's `cascades`
    factory is derived from this registry (RADD-745)."""
    _BINDINGS[binding.entity_type] = binding


def bindings() -> list[ParentBinding]:
    """Every registered parent — `gc.cascades` is built from this."""
    return list(_BINDINGS.values())


def binding_for(entity_type: str) -> ParentBinding:
    binding = _BINDINGS.get(entity_type)
    if binding is None:
        raise NotFoundError(AttachmentEntity.ATTACHMENT, f"parent type {entity_type!r}")
    return binding


# --- the item binding (attachments' own) --------------------------------------


async def _item_guard(
    session: AsyncSession, user: User, item_id: uuid.UUID, permission: Permission
) -> None:
    # RADD-823: read-resolution through THE item seam; other atoms layer on top.
    item, project, _perms = await items_service.require_readable_item(session, item_id, user)
    if permission is not Permission.ITEM_READ:
        permissions = await authz.require(session, user, permission, project=project)
        # RADD-1304: a relation-qualified grant (`attachment.create@own` on the
        # Baseline) holds only on the rows its relation names.
        await items_service.ensure_item_relation(session, user, item, permissions, permission)


async def _item_read(session: AsyncSession, user: User, item_id: uuid.UUID) -> None:
    await _item_guard(session, user, item_id, Permission.ITEM_READ)


async def _item_write(session: AsyncSession, user: User, item_id: uuid.UUID) -> None:
    """Upload + delete-own: `attachment.create`, NOT `item.update` (RADD-790) — a
    role that may discuss an issue but not edit it must still paste a screenshot."""
    await _item_guard(session, user, item_id, Permission.ATTACHMENT_CREATE)


async def _item_admin(session: AsyncSession, user: User, item_id: uuid.UUID) -> None:
    await _item_guard(session, user, item_id, Permission.PROJECT_MANAGE)


async def _item_project_id(session: AsyncSession, item_id: uuid.UUID) -> uuid.UUID | None:
    item = await items_service.require_item(session, item_id)
    return item.project_id


register_parent(
    ParentBinding(
        entity_type=AttachmentParentType.ITEM.value,
        deleted_event=str(ItemEvent.DELETED),
        require_read=_item_read,
        require_write=_item_write,
        require_admin=_item_admin,
        project_id_of=_item_project_id,
    )
)
