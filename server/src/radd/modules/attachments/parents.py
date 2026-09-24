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
    #: The event emitted when a parent of this kind is destroyed (RADD-744).
    #:
    #: The polymorphic parent has no FK, so `gc.py` is what collects the rows AND
    #: THE BYTES. It used to decide from a hardcoded map, which meant a parent
    #: registered by a PLUGIN — the seam this registry exists for — got no
    #: cleanup at all, and its files sat on a storage host forever with nothing
    #: pointing at them.
    #:
    #: Required, not defaulted: `""` would reintroduce the same bug in a quieter
    #: form, a binding that looks complete and silently leaks. Failing loudly at
    #: import is the better failure.
    deleted_event: str
    space_id_of: ProjectOf | None = None


_BINDINGS: dict[str, ParentBinding] = {}


def register_parent(binding: ParentBinding) -> None:
    """Register a parent. Its cleanup follows automatically: the plugin's
    `cascades` factory is derived from THIS registry (RADD-745), so a binding
    cannot exist without one. A binding without cleanup would leak rows AND
    BYTES on a storage host, silently and forever."""
    _BINDINGS[binding.entity_type] = binding


def bindings() -> list[ParentBinding]:
    """Every registered parent — the GC builds its event map from this."""
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
    """Upload + delete-own. `attachment.create`, NOT `item.update` (RADD-790).

    Those are different authorities and conflating them broke the obvious case: a
    role of `item.read` + `comment.write` — someone who may discuss an issue but
    not edit it — posted a comment fine and then 403'd on the pasted screenshot,
    which reads as "commenting is broken". `item.update` still implies this atom,
    so nothing that could attach before has stopped being able to.
    """
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
